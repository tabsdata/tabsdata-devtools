#
# Copyright 2026 Tabsdata Inc.
#

import json
import pathlib

import pytest

SUITE = {
    "domains": [
        {"name": "fs", "system": "fs"},
        {"name": "world", "system": "fs", "model": "world", "data": "s"},
    ],
    "collections": [
        {
            "name": "src",
            "type": "local_file_in",
            "connection_template": "connection-file:connections/local_file_in.yaml",
            "group": "sources",
            "domains": {"D0": "world"},
        },
        {"name": "ops", "type": "transform", "group": "ops"},
    ],
    "functions": [
        {"collection": "src", "functionpath": "functions/f.py::pub"},
        {"collection": "ops", "functionpath": "functions/f.py::tfr"},
    ],
    "triggers": [
        {"collection": "src", "function": "pub", "detached": True},
        {"collection": "src", "function": "pub2", "detached": True},
        {"collection": "ops", "function": "tfr", "detached": False},
        {"collection": "src", "function": "pub3", "detached": True},
    ],
}


@pytest.fixture
def xp_root(tmp_path, monkeypatch):
    root = tmp_path / "xp"
    (root / "suites" / "demo" / "functions").mkdir(parents=True)
    (root / "connections").mkdir()
    (root / "suites" / "demo" / "one.json").write_text(json.dumps(SUITE))
    (root / "suites" / "demo" / "two.json").write_text(
        json.dumps({"domains": [], "collections": [], "functions": [], "triggers": []})
    )
    (root / "suites" / "demo" / "notes.json").write_text(
        json.dumps({"_comment": "not a suite"})
    )
    (root / "suites" / "demo" / "functions" / "f.py").write_text(
        "# ${D0__DB} is the domain\n"
    )
    (root / "connections" / "local_file_in.yaml").write_text(
        "kind: connectionDef\ntype: tabsdatak.conn.localfile:LocalFileSrcConn\nspec:\n  base_path: ''\n  token: $secret:D0__TOKEN\n  label: '${D0__DB}_x'\n"
    )
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    monkeypatch.delenv("_TDD_XP_SCRATCH", raising=False)
    monkeypatch.delenv("_TDD_XP_PARENT", raising=False)
    return root


def _run(argv):
    from tabsdata_dev.tool import xp

    return xp.cli.run(
        xp.NAME,
        xp.DESCRIPTION,
        xp.body,
        argv=argv,
        configure=xp.configure,
    )


def _suites_dir(xp_root):
    return ["--suites-dir", str(xp_root / "suites")]


def test_a_mistyped_suite_selector_names_the_one_it_meant(tmp_path):
    """A selector is `<type>/<name>` and the name alone is what a reader
    remembers -- `--suite s3` for `cloud-connectors/s3`, which is exactly the
    shape that stopped working when the connectors were split in two. The
    refusal names the candidate instead of sending them to `list-suites`.

    Offered, never accepted: a bare name is unique today and need not stay so,
    and resolving one silently would one day run a suite nobody asked for.
    """
    from tabsdata_dev.tool.xp import suites

    root = tmp_path / "suites"
    for rel in ("cloud/s3.json", "cloud/gcs.json", "local/s3_files.json"):
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"domains": [], "collections": [], "functions": []}')

    # the leaf is exact, and one suite has it
    assert suites._did_you_mean(root, "s3") == "; did you mean cloud/s3?"
    # no leaf, but the text appears in more than one
    assert "cloud/gcs" in suites._did_you_mean(root, "c")
    assert suites._did_you_mean(root, "c").startswith("; did you mean one of ")
    # nothing like it: the listing is the only advice worth giving
    assert suites._did_you_mean(root, "zzz") == "; `list-suites` shows what is there"


def test_suite_selectors_resolve_under_a_suites_dir_or_as_paths(xp_root):
    from tabsdata_dev.tool.xp import suites

    one = xp_root / "suites" / "demo" / "one.json"
    root = xp_root / "suites"
    assert suites.resolve("demo/one", root) == (one, None)  # a selector under the dir
    assert suites.resolve("demo/one.json", root) == (one, None)
    assert suites.resolve(str(one)) == (one, None)  # an explicit path still works
    assert suites.resolve(str(one.with_suffix("")))[0] == one  # .json tolerated
    path, lanes = suites.resolve("demo", root)
    assert path == root / "demo" and [p.stem for p in lanes] == ["one", "two"]
    assert suites.label(one) == "demo/one" and suites.label(path) == "demo"
    assert (
        suites.token(one) == "demo_one"
        and suites.token(one.with_name("suite.json")) == "demo"
    )
    assert suites.base_dir(one.parent) == xp_root  # the ancestor holding connections/
    rows = suites.list_suites(root)
    assert [r["suite"] for r in rows] == ["demo/one", "demo/two"] and rows[0][
        "triggers"
    ] == 4


def test_pointers_live_under_the_tdd_data_dir(xp_root, tmp_path):
    from tabsdata_dev.tool.xp import pointers, suites

    one = xp_root / "suites" / "demo" / "one.json"
    pointers.write_instance("i1", one)
    assert pointers.store() == tmp_path / "tdd" / "data" / "xp"
    inst = pointers.load_instance("i1")
    assert (
        inst.suite_file == str(one)
        and inst.base_dir == str(xp_root)
        and inst.type == "demo"
    )
    assert inst.domain_full("fs") == "i1_fs"
    pointers.write_project("p1", "i1")
    assert (
        pointers.load_project("p1") == "i1"
        and pointers.suite_of_project("p1") == "demo/one"
    )
    pointers.write_group_instance("g", ["g_one", "g_two"], one.parent)
    assert (
        pointers.instance_group("g") == ["g_one", "g_two"]
        and pointers.suite_of_instance("g") == "demo"
    )
    assert (
        suites.label(
            pathlib.Path(pointers.doc_of(pointers.instance_file("g"))["suite"])
        )
        == "demo"
    )


def test_trigger_batches_gate_on_attached_triggers(xp_root):
    from tabsdata_dev.tool.xp import project
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", xp_root / "suites" / "demo" / "one.json")
    batches = [[t.function for t in b] for b in project.trigger_batches(inst.triggers)]
    assert batches == [["pub", "pub2"], ["tfr"], ["pub3"]]


def test_connection_prep_resolves_secrets_and_interpolates(xp_root, monkeypatch):
    from tabsdata_dev.tool.xp import conn, state

    monkeypatch.delenv("D0__TOKEN", raising=False)
    doc = conn.prepare_conn(
        xp_root / "connections" / "local_file_in.yaml",
        {"D0__TOKEN": "s3cr3t", "D0__DB": "xp_db", "D0__BASE_PATH": "/data/xp"},
    )
    assert (
        "token: secret:s3cr3t" in doc
        and "label: xp_db_x" in doc
        and "base_path: /data/xp" in doc
    )
    assert (
        conn.abs_base_path("bucket/run") == "/bucket/run"
        and conn.abs_base_path("secret:C:\\x") == "secret:C:\\x"
    )
    with pytest.raises(state.XpError, match="no value for"):
        conn.interpolate("${D0__NOPE}", {}, "here")


def test_domain_manifest_entries_carry_the_keys_tdd_domain_takes(xp_root):
    from tabsdata_dev.tool.xp import domains
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i1", xp_root / "suites" / "demo" / "one.json")
    fs, world = inst.domains
    entry = domains.domain_entry(inst, world, "20260829T000000")
    assert (
        entry["name"] == "i1_world"
        and entry["sys"] == "fs"
        and entry["model"] == "world"
        and entry["size"] == 10
    )
    assert entry["name-in-system"].startswith("xp_") and entry[
        "name-in-system"
    ].endswith("_world")
    # stable across runs of the same timestamp (a partial failure reuses the container)
    assert (
        entry["name-in-system"]
        == domains.domain_entry(inst, world, "20260829T000000")["name-in-system"]
    )
    assert "model" not in domains.domain_entry(inst, fs, "x")


def test_dry_run_one_shot_prints_the_tdd_commands_and_touches_no_server(
    xp_root, capsys
):
    rc = _run(
        [
            "one-shot",
            "--suite",
            "demo/one",
            *_suites_dir(xp_root),
            "--project",
            "p",
            "--dry-run",
        ]
    )
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = [line for line in out.splitlines() if line.startswith("tdd ")]
    assert (
        lines[0].startswith("tdd domain create --manifest ")
        and "--fail-fast" in lines[0]
    )
    assert "tdd tdk project create --name p" in "\n".join(lines)
    assert (
        "tdd tdk collection create --proj p --name src --group sources --conn-file -"
        in lines
    )
    assert any(
        line.startswith("tdd tdk fn register --update --proj p --coll src --path ")
        for line in lines
    )
    assert "tdd tdk fn trigger --proj p --coll src --name pub --plan-name" in "\n".join(
        lines
    ) and "--detach" in "\n".join(lines)
    assert "tdd tdk trx list --proj p --monitor" in lines
    assert any(line.startswith("tdd tdk collection delete --proj p") for line in lines)
    assert any(
        line.startswith("tdd domain destroy --manifest") and line.endswith("--force")
        for line in lines
    )
    # the ok summary is the last line on stdout, the progress went to stderr
    assert "summary" in out.splitlines()[-1] and "all ok" in out.splitlines()[-1]
    assert "create-domain" in err and "register-fn" in err


def test_json_stream_carries_steps_and_ends_in_one_ok(xp_root, capsys):
    rc = _run(
        [
            "create-instance",
            "--suite",
            "demo/one",
            *_suites_dir(xp_root),
            "--instance",
            "i2",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    rc = _run(["run-project", "--project", "nope", "--dry-run", "--format", "json"])
    out, _ = capsys.readouterr()
    events = [json.loads(line) for line in out.splitlines()]
    assert all(e["command"] == "xp" for e in events)
    assert (
        events[-1]["event"] == "error"
        and "project 'nope' not found" in events[-1]["message"]
    )
    assert rc == 1


def test_bench_rejects_a_single_file_and_list_suites_reports(xp_root, capsys):
    assert (
        _run(["bench", "--suite", "demo/one", *_suites_dir(xp_root), "--dry-run"]) == 1
    )
    assert "bench needs a suite DIR" in capsys.readouterr().err
    assert _run(["list-suites", *_suites_dir(xp_root), "--format", "json"]) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event"] == "ok" and [s["suite"] for s in last["suites"]] == [
        "demo/one",
        "demo/two",
    ]
    assert last["builtin"] is False


def test_the_login_probe_does_not_open_an_unlabelled_reporter(
    xp_root, monkeypatch, capsys
):
    # one-shot checks the session BEFORE it opens its reporter; that probe used to
    # create a bare reporter named after the tool, and every progress line then
    # read `xp -` instead of the suite, with a bare `done` instead of the
    # summary at the end.
    import subprocess

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import shell, state

    state.bind(render.Renderer("xp"), type("A", (), {})())
    # Scoped: an undo() here would also drop the fixture's TDD_DIR and write the
    # pointers below into the real store.
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(
            subprocess,
            "run",
            lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "ok", ""),
        )
        shell.require_login()
    assert state.run.reporter is None
    assert (
        _run(
            [
                "create-instance",
                "--suite",
                "demo/one",
                *_suites_dir(xp_root),
                "--instance",
                "lbl",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _run(["create-domains", "--instance", "lbl", "--dry-run"]) == 0
    out, err = capsys.readouterr()
    assert any(
        line.startswith("demo/one - [1/2] - create-domain") for line in err.splitlines()
    )
    assert out.splitlines()[-1].startswith("demo/one - summary - 2 step(s), all ok")


def test_the_built_in_suites_ship_with_the_package_and_export(
    tmp_path, monkeypatch, capsys
):
    from tabsdata_dev.tool.xp import suites

    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    root = suites.builtin_root()
    assert (root / "suites" / "test" / "test.json").is_file() and (
        root / "connections" / "datagen_in.yaml"
    ).is_file()
    path, lanes = suites.resolve("test/test")
    assert path == root / "suites" / "test" / "test.json" and lanes is None
    assert suites.resolve("container-connectors")[1]  # a type dir fans out
    assert (
        suites.base_dir(path.parent) == root
    )  # connection-file: refs resolve against the shipped templates
    assert _run(["list-suites", "--format", "json"]) == 0
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["builtin"] is True and len(last["suites"]) > 100
    assert {"test/test", "container-connectors/localfile"} <= {
        s["suite"] for s in last["suites"]
    }
    out = tmp_path / "xp"
    assert _run(["export-suites", "--dir", str(out)]) == 0
    assert (out / "suites" / "test" / "test.json").is_file() and (
        out / "connections" / "datagen_in.yaml"
    ).is_file()
    assert not list(out.rglob("__pycache__"))
    assert _run(["export-suites", "--dir", str(out)]) == 1
    assert "--force" in capsys.readouterr().err
    assert _run(["export-suites", "--dir", str(out), "--force"]) == 0
    assert (
        suites.resolve("test/test", out / "suites")[0]
        == out / "suites" / "test" / "test.json"
    )


def test_a_lane_step_re_emitted_with_model_keys_does_not_clash(xp_root, capsys):
    # The dispatcher hands emit_step a child's whole JSON event -- command,
    # event and message included -- which used to collide with the renderer's
    # own arguments (TypeError: multiple values for 'message') on every fan-out.
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import reporter, state

    state.bind(render.Renderer("xp", fmt="json"), type("A", (), {})())
    event = {
        "command": "xp",
        "event": "warn",
        "message": "demo/one - [1/2] - create-domain - d - 0.10s FAILED",
        "xp": "step",
        "suite": "demo/one",
        "n": 1,
        "total": 2,
        "action": "create-domain",
        "path": "d",
        "seconds": 0.1,
        "ok": False,
        "note": "",
        "step_error": "boom",
        "log": "/tmp/x.log",
    }
    reporter.emit_step({**event, "lane": "one"}, prefix="[1/4] ")
    line = json.loads(capsys.readouterr().out.strip())
    assert (
        line["event"] == "warn"
        and line["message"].startswith("[1/4] demo/one - [1/2]")
        and line["lane"] == "one"
    )


def test_scratch_root_is_honoured_only_from_a_parent_xp(monkeypatch, tmp_path, capsys):
    """_TDD_XP_SCRATCH is xp's private hand-off to its fan-out children: a
    value in the environment counts only with the parent's pid beside it."""
    import os

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import reporter, state

    # a renderer on THIS test's streams, not one an earlier test left behind
    state.run = state.Run(out=render.Renderer(state.TOOL))
    stale = tmp_path / "stale"
    monkeypatch.setenv(state.SCRATCH_ENV, str(stale))
    monkeypatch.delenv(state.SCRATCH_PARENT_ENV, raising=False)
    state.run.scratch = None
    dest = reporter.scratch_init("lane")
    assert stale not in dest.parents
    assert state.SCRATCH_ENV in capsys.readouterr().err

    monkeypatch.setenv(state.SCRATCH_PARENT_ENV, str(os.getppid()))
    state.run.scratch = None
    dest = reporter.scratch_init("lane")
    assert dest == stale / "lane"
    assert capsys.readouterr().err == ""
    state.run.scratch = None


def test_list_systems_reports_each_required_system_and_fails_on_a_missing_one(
    xp_root, monkeypatch, capsys
):
    from tabsdata_dev.tool.xp import project

    needed = sorted({d["system"] for d in SUITE["domains"]})
    assert needed, "the fixture suite must need at least one system"

    monkeypatch.setattr(
        project, "_store_systems", lambda: {n: f"{n}-type" for n in needed}
    )
    rc = _run(
        [
            "list-systems",
            "--suite",
            "demo/one",
            "--suites-dir",
            str(xp_root / "suites"),
            "--format",
            "json",
        ]
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    ok = [e for e in events if e["event"] == "ok"][0]
    assert rc == 0 and ok["missing"] == []
    assert [r["name"] for r in ok["systems"]] == needed
    assert all(r["present"] and r["type"] == f"{r['name']}-type" for r in ok["systems"])

    monkeypatch.setattr(project, "_store_systems", lambda: {})
    rc = _run(
        [
            "list-systems",
            "--suite",
            "demo",
            "--suites-dir",
            str(xp_root / "suites"),
            "--format",
            "json",
        ]
    )
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    err = [e for e in events if e["event"] == "error"][0]
    assert rc == 1
    assert all(n in err["message"] for n in needed)
    # the table still came out, MISSING marked, before the failure
    notes = " ".join(e["message"] for e in events if e["event"] == "info")
    assert "MISSING" in notes and needed[0] in notes


def test_a_plan_name_fits_tabsdatas_hundred_characters():
    """tabsdata's ExecutionName is max_len 100 and the trigger is refused
    outright above it. xp names a project `<instance>_<lane>`, so putting both
    in spent the instance twice -- which is what took a real EKS smoke run two
    characters over and failed the only xp stage of an otherwise green run."""
    from tabsdata_dev.tool.xp.project import PLAN_NAME_MAX, plan_name

    ts = "20260908_204308"
    # a one-shot lane: `pointers.load_instance(load_project(...))` gives the
    # lane's own instance, which carries the project's name exactly
    project = "sm_t210a__xp_20260908T204250_test_test"
    instance = project

    # the run that failed, at 102 characters the old way
    assert len(f"{ts}_{instance}_{project}_test_pub") > PLAN_NAME_MAX
    name = plan_name(ts, instance, project, "test_pub")
    assert len(name) <= PLAN_NAME_MAX
    assert name == f"{ts}_{project}_test_pub"  # the instance is not repeated
    assert len(name) == 63 and project in name and "test_pub" in name

    # an instance that is not a prefix of the project is still named
    other = plan_name(ts, "inst", "proj", "fn")
    assert other == f"{ts}_inst_proj_fn"

    # and a name that overflows anyway keeps the ends and stays unique
    long_project = f"{instance}_" + "x" * 200
    a = plan_name(ts, instance, long_project, "fn_one")
    b = plan_name(ts, instance, long_project + "y", "fn_one")
    assert len(a) <= PLAN_NAME_MAX and len(b) <= PLAN_NAME_MAX
    assert a.startswith(ts) and a.endswith("fn_one")
    assert a != b, "two truncated plans must not collide"
