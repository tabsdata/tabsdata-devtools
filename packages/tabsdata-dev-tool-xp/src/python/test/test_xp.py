#
# Copyright 2026 Tabsdata Inc.
#

import json
import pathlib

import pytest


def calls(name, system, model=None, size=None, *data_opts):
    """A domain as a domains stage writes it: its create and, seeded, its
    create-model and create-data."""
    out = [{"name": name, "command": "create", "options": ["--sys", system]}]
    if model:
        out.append(
            {"name": name, "command": "create-model", "options": ["--model", model]}
        )
        out.append(
            {
                "name": name,
                "command": "create-data",
                "options": ["--size", str(size or 1), *data_opts],
            }
        )
    return out


SUITE = {
    "domains": [*calls("fs", "fs"), *calls("world", "fs", "world", 10)],
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


def _stages(doc: dict) -> list:
    """A suite written as its sections, as the list of stages xp reads."""
    stages = [
        {k: doc[k]}
        for k in ("domains", "collections", "functions", "triggers")
        if doc.get(k)
    ]
    return stages + [{"monitor": True}]


@pytest.fixture
def xp_root(tmp_path, monkeypatch):
    root = tmp_path / "xp"
    (root / "suites" / "demo" / "functions").mkdir(parents=True)
    (root / "connections").mkdir()
    (root / "suites" / "demo" / "one.json").write_text(json.dumps(_stages(SUITE)))
    (root / "suites" / "demo" / "two.json").write_text(json.dumps([{"monitor": True}]))
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


def test_a_creates_backend_name_is_per_run_and_stable_within_one(xp_root):
    """xp names the backend object itself (`--name-in-system`): the user, the
    run's timestamp and a tag of the logical domain -- the same for the same
    run, so a partial failure re-run reuses the container."""
    from tabsdata_dev.tool.xp import domains
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i1", xp_root / "suites" / "demo" / "one.json")
    assert [(d.name, d.system) for d in inst.domains] == [("fs", "fs"), ("world", "fs")]
    name = domains.name_in_system(inst, "world", "20260829T000000")
    assert name.startswith("xp_") and name.endswith(
        "_20260829T000000_" + name.split("_")[-2] + "_world"
    )
    assert name == domains.name_in_system(inst, "world", "20260829T000000")
    assert name != domains.name_in_system(inst, "fs", "20260829T000000")


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
    # a domains stage is its calls, as written: each domain's create first
    assert lines[0].startswith(
        "tdd domain create --domain p_fs --sys fs --name-in-system "
    )
    assert lines[1].startswith("tdd domain create --domain p_world --sys fs ")
    assert lines[2:4] == [
        "tdd domain create-model --domain p_world --model world",
        "tdd domain create-data --domain p_world --size 10",
    ]
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


def test_profile_reaches_every_tdk_call_and_only_when_given(xp_root, capsys):
    def tdk_lines(*extra):
        rc = _run(
            [
                "one-shot",
                "--suite",
                "demo/one",
                *_suites_dir(xp_root),
                "--project",
                "p",
                "--dry-run",
                *extra,
            ]
        )
        out, err = capsys.readouterr()
        assert rc == 0, err
        return [line for line in out.splitlines() if line.startswith("tdd tdk ")]

    given = tdk_lines("--profile", "sm_a")
    # after the command: tdk gives --profile to each command, not the root group
    assert given and all(line.endswith(" --profile sm_a") for line in given)
    assert "tdd tdk trx list --proj p --monitor --profile sm_a" in given
    # absent, tdk keeps its own default connection: no option at all
    assert all("--profile" not in line for line in tdk_lines())


def test_a_fan_out_hands_the_profile_to_every_child_that_calls_tdk(
    xp_root, monkeypatch, capsys
):
    from tabsdata_dev.tool.xp import lanes

    children = []

    def dispatch(label, argvs, **kw):
        children.extend(argv for _, argv in argvs)
        return []

    monkeypatch.setattr(lanes, "dispatch", dispatch)
    rc = _run(
        [
            "one-shot",
            "--suite",
            "demo",
            *_suites_dir(xp_root),
            "--project",
            "g",
            "--dry-run",
            "--profile",
            "sm_a",
        ]
    )
    _, err = capsys.readouterr()
    assert rc == 0, err
    verbs = {}
    for argv in children:
        verbs.setdefault(argv[argv.index("xp") + 1], []).append(argv)
    # each lane runs its own stages through run-suite, which reaches tdk
    for verb in ("run-suite", "destroy-project"):
        assert verbs[verb] and all(
            argv[argv.index("--profile") + 1] == "sm_a" for argv in verbs[verb]
        ), verb
    # the domain verbs never reach tdk and take no --profile
    assert all("--profile" not in argv for argv in verbs["destroy-domains"])


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
        line.startswith("demo/one - [1/4] - create-domain") for line in err.splitlines()
    )
    assert out.splitlines()[-1].startswith("demo/one - summary - 4 step(s), all ok")


def test_the_built_in_suites_are_carried_at_the_repo_root_and_packed_into_a_wheel():
    """The XP tree is 800-odd of tabsdata-xp's own files, read and edited at the
    repo root -- so that is where it lives, and a wheel build copies it in
    beside the module (force-include). An editable install copies nothing, so
    the tool has to find both layouts, and the pyproject has to name the very
    directory `builtin_root()` probes for or a wheel would carry no suites at
    all. Same arrangement as the smoke scripts.
    """
    import tomllib

    from tabsdata_dev.tool.xp import suites

    pkg = pathlib.Path(__file__).parents[3]
    repo = pkg.parents[1]

    # the checkout keeps them at the root, and nothing was left in the package
    assert (repo / suites.TREE_DIR / "suites").is_dir()
    assert (repo / suites.TREE_DIR / "connections").is_dir()
    module = pkg / "src" / "python" / "main" / "tabsdata_dev" / "tool" / "xp"
    assert not (module / suites.TREE_DIR).exists()

    wheel = tomllib.loads((pkg / "pyproject.toml").read_text(encoding="utf-8"))
    assert wheel["tool"]["hatch"]["build"]["targets"]["wheel"]["force-include"] == {
        f"../../{suites.TREE_DIR}": f"tabsdata_dev/tool/xp/{suites.TREE_DIR}"
    }

    # and whichever of the two layouts this install is, that is what was found
    root = suites.builtin_root()
    assert root.name == suites.TREE_DIR
    assert (root / "suites").is_dir() and (root / "connections").is_dir()


def test_the_built_in_suites_are_the_default_and_export(tmp_path, monkeypatch, capsys):
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

    needed = sorted(
        {d["options"][1] for d in SUITE["domains"] if d["command"] == "create"}
    )
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


def test_a_failed_transaction_leaves_its_worker_logs_in_the_scratch_dir(
    xp_root, monkeypatch, capsys
):
    """The instance is torn down right after a failed run, so the monitor saves
    every worker's log while the server still has them -- one fetch per worker,
    never `trx logs`, which prompts when several ran. A fetch that fails is
    named, and the failed transactions stay the error."""
    import subprocess

    from tabsdata_dev.tool.xp import shell

    trx = [
        {"id": "tx-1", "status": "L", "collection": "ch_s3"},
        {"id": "tx-2", "status": "Published", "collection": "ok"},
    ]
    workers = {"tx-1": [{"id": "w-a", "status": "Failed"}, {"id": "w-b"}]}
    calls = []

    def fake(argv, check, stdin_text=None, env=None):
        args = argv[argv.index("tdk") + 1 :]
        calls.append(args)
        out, rc = "", 0
        if args[:2] == ["trx", "list"] and "--monitor" not in args:
            out = json.dumps(trx)
        elif args[:2] == ["worker", "list"]:
            out = json.dumps(workers[args[args.index("--trx") + 1]])
        elif args[:2] == ["worker", "logs"]:
            wid = args[args.index("--worker") + 1]
            if wid == "w-b":
                return subprocess.CompletedProcess(argv, 1, "", "│ Failed: gone │")
            pathlib.Path(args[args.index("--file") + 1]).write_text(f"log of {wid}")
        return subprocess.CompletedProcess(argv, rc, out, "")

    monkeypatch.setattr(shell, "run_cmd", fake)
    rc = _run(["monitor-project", "--project", "p1", "--format", "json"])
    events = [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]
    err = [e for e in events if e["event"] == "error"][0]
    assert rc == 1 and "1 failed transaction(s)" in err["message"]
    assert not any(a[:2] == ["trx", "logs"] for a in calls)
    assert not any("tx-2" in a for a in calls)  # only the failed one is fetched

    scratch = pathlib.Path(err["scratch"])
    saved = scratch / "trx-logs" / "tx-1" / "w-a.log"
    assert saved.read_text() == "log of w-a"
    assert str(saved) in err["message"] and "w-b: Failed: gone" in err["message"]
    assert str(saved) in (scratch / "errors.log").read_text()


def _fake_monitor(monkeypatch, watches):
    """Stand in for tdk and the clock: each `trx list --monitor` takes the next
    (seconds it runs, exit code) from ``watches``; the project has no failed
    transactions."""
    import subprocess
    import types

    from tabsdata_dev.tool.xp import project, shell

    now = [0.0]
    queue = list(watches)
    watched = []

    def fake(argv, check, stdin_text=None, env=None):
        args = argv[argv.index("tdk") + 1 :]
        if args[:2] == ["trx", "list"] and "--monitor" in args:
            seconds, rc = queue.pop(0)
            now[0] += seconds
            watched.append(rc)
            return subprocess.CompletedProcess(argv, rc, "", "│ Connection reset │")
        return subprocess.CompletedProcess(argv, 0, "[]", "")

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(shell, "run_cmd", fake)
    monkeypatch.setattr(
        project, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
    )
    return watched


def _monitor_events(capsys):
    rc = _run(["monitor-project", "--project", "p1", "--format", "json"])
    return rc, [
        json.loads(line)
        for line in capsys.readouterr().out.splitlines()
        if line.startswith("{")
    ]


def test_the_monitor_watches_again_after_the_connection_drops(
    xp_root, monkeypatch, capsys
):
    """A dropped port-forward ended every lane it was watching although their
    transactions ran on; the monitor only reads, so it is started again."""
    watched = _fake_monitor(monkeypatch, [(40, 1), (1, 1), (10, 0)])
    rc, events = _monitor_events(capsys)
    assert rc == 0 and watched == [1, 1, 0]
    notes = [e["message"] for e in events if e.get("xp") == "note"]
    assert sum("watching again" in n and "Connection reset" in n for n in notes) == 2


def test_the_monitor_gives_up_once_the_grace_period_is_spent(
    xp_root, monkeypatch, capsys
):
    from tabsdata_dev.tool.xp import project

    watched = _fake_monitor(monkeypatch, [(1, 1)] * 100)
    rc, events = _monitor_events(capsys)
    err = [e for e in events if e["event"] == "error"][0]
    assert rc == 1 and "kept failing for 120s" in err["message"]
    # every attempt costs a pause plus its own second: the grace bounds them
    grace = project.MONITOR_OUTAGE_GRACE
    per_try = project.MONITOR_RETRY_PAUSE + 1
    assert len(watched) == int(grace // per_try) + 1


def test_a_watch_that_reached_the_server_restarts_the_outage_clock(
    xp_root, monkeypatch, capsys
):
    """Two outages of 100s each, apart: neither alone spends the grace, so the
    run survives both."""
    outage = [(1, 1)] * 16  # 16 x (1s + 5s pause) = 96s down
    watched = _fake_monitor(monkeypatch, [*outage, (60, 1), *outage, (5, 0)])
    rc, _ = _monitor_events(capsys)
    assert rc == 0 and watched[-1] == 0


def test_a_failed_lane_shows_its_own_error_not_just_its_exit_code(
    xp_root, monkeypatch, capsys
):
    """A lane speaks json, so its only non-event output is usually nothing:
    the reason it failed is its own error event, and the console shows that
    -- without the lane's summary block, which its log keeps."""
    import sys

    from tabsdata_dev.tool.xp import lanes, state

    child = (
        "import json; print(json.dumps({'command': 'xp', 'event': 'error', "
        "'xp': 'summary', 'message': 'KEY must be set (see --secret-env)\\n"
        "demo/one - summary - 0 step(s), 0 ok, run failed in 0.0s - /tmp/x'}));"
        " raise SystemExit(1)"
    )
    from tabsdata_dev.common.core import render

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    failed = lanes.dispatch("t", [("l1", [sys.executable, "-c", child])], fatal=False)
    err = capsys.readouterr().err
    assert failed == ["l1"]
    assert "FAILED lane l1 -- 1 line(s) of detail" in err
    assert "KEY must be set (see --secret-env)" in err
    assert "exit 1" not in err and " - summary - 0 step(s)" not in err


def argparse_ns(**kw):
    import argparse

    return argparse.Namespace(**kw)


def test_one_shot_refuses_without_the_crypto_key_before_writing_anything(
    xp_root, monkeypatch, capsys
):
    from tabsdata_dev.tool.xp import pointers, shell

    monkeypatch.delenv("_TDD_CRYPTO_KEY", raising=False)
    monkeypatch.setattr(shell, "require_login", lambda: None)
    rc = _run(["one-shot", "--suite", "demo", *_suites_dir(xp_root), "--project", "g"])
    err = capsys.readouterr().err
    assert rc == 1 and "the domain crypto key is not set: _TDD_CRYPTO_KEY" in err
    assert "tdd env set --crypto" in err
    assert not pointers.instance_file("g").exists()


def _live_instance(xp_root, script):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    return build_instance("i", _live_suite(xp_root, script))


def _dom(name, command, *options):
    doc = {"name": name, "command": command}
    if options:
        doc["options"] = list(options)
    return doc


LIVE = [
    {
        "name": "cycle",
        "repeat": 3,
        "live": [
            {"name": "load", "domain": _dom("world", "create-data")},
            {
                "name": "churn",
                "repeat": 10,
                "live": [
                    {"name": "pause", "sleep": "1s"},
                    {
                        "name": "city",
                        "domain": _dom(
                            "world",
                            "modify-data",
                            "--entity",
                            "city",
                            "--ops",
                            "Insert",
                        ),
                    },
                    {"name": "files", "domain": _dom("fs", "modify-data")},
                ],
            },
            {"name": "empty", "domain": _dom("world", "delete-data")},
            {"name": "drop", "domain": _dom("world", "delete-model")},
            {
                "name": "model",
                "domain": _dom("world", "create-model", "--force", "--model", "world"),
            },
        ],
    }
]


def _live_suite(xp_root, live=LIVE):
    path = xp_root / "suites" / "live" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_stages(SUITE) + [{"live": live}, {"monitor": True}]))
    return path


def _instance(xp_root, name="i"):
    assert (
        _run(
            [
                "create-instance",
                "--suite",
                "live/one",
                *_suites_dir(xp_root),
                "--instance",
                name,
            ]
        )
        == 0
    )


def test_a_live_script_counts_its_calls_through_every_loop(xp_root):
    from tabsdata_dev.tool.xp import live
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", _live_suite(xp_root))
    # 3 x (load + 10 x (city + files) + empty + drop + model); sleeps are no calls
    assert live.count(inst.live) == 3 * (1 + 10 * 2 + 3)


@pytest.mark.parametrize(
    "script, why",
    [
        ([{"domain": _dom("world", "delete-data")}], "name"),
        ([{"name": "1st", "sleep": "1s"}], "a letter"),
        ([{"name": "x"}], "exactly one of 'domain', 'sleep', 'wait' or 'live'"),
        (
            [{"name": "x", "sleep": "1s", "wait": ["y"]}],
            "exactly one of .* \\(has sleep, wait\\)",
        ),
        ([{"name": "x", "domain": _dom("world", "destroy")}], "is not one of"),
        ([{"name": "x", "domain": _dom("nope", "delete-data")}], "does not define"),
        (
            [{"name": "x", "domain": _dom("world", "modify-data", "--format", "json")}],
            "set by xp itself: --format",
        ),
        (
            [
                {
                    "name": "x",
                    "domain": {"name": "world", "command": "delete-data", "opts": []},
                }
            ],
            "Extra inputs",
        ),
        (
            [{"name": "x", "sleep": "1s", "blocking": False}],
            "only a 'domain' or 'live' entry",
        ),
        (
            [{"name": "x", "repeat": 2, "domain": _dom("world", "delete-data")}],
            "'repeat' goes with 'live'",
        ),
        ([{"name": "x", "repeat": 0, "live": []}], "repeat must be >= 1"),
        (
            [
                {"name": "x", "sleep": "1s"},
                {"name": "x", "sleep": "1s"},
            ],
            "'x' is used twice",
        ),
        (
            [{"name": "w", "wait": ["later"]}, {"name": "later", "sleep": "1s"}],
            "not an entry before it",
        ),
        (
            # out of reach: inside another entry's nested live
            [
                {
                    "name": "g",
                    "live": [{"name": "inner", "domain": _dom("world", "delete-data")}],
                },
                {"name": "w", "wait": ["inner"]},
            ],
            "'inner', which is not an entry before it",
        ),
        (
            # the entry that contains the wait: it would wait for itself
            [{"name": "g", "live": [{"name": "w", "wait": ["g"]}]}],
            "'g', which is not an entry before it",
        ),
        (
            [{"name": "s", "sleep": "1s"}, {"name": "w", "wait": ["s"]}],
            "a sleep entry",
        ),
    ],
)
def test_a_live_script_is_refused_when_the_suite_is_read(xp_root, script, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _live_suite(xp_root, script))


def test_a_wait_reaches_entries_before_it_here_and_in_enclosing_lists(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    script = [
        {"name": "bg", "blocking": False, "domain": _dom("world", "modify-data")},
        {
            "name": "g",
            "repeat": 2,
            "live": [
                {"name": "one", "blocking": False, "domain": _dom("fs", "modify-data")},
                {"name": "w", "wait": ["one", "bg"]},  # a sibling and an outer entry
            ],
        },
        {"name": "w2", "wait": "g"},  # one name may be a bare string
    ]
    assert build_instance("i", _live_suite(xp_root, script)).live[2].wait == ["g"]


def test_dry_run_live_domains_prints_the_script_in_order(xp_root, capsys):
    _live_suite(xp_root)
    _instance(xp_root)
    capsys.readouterr()
    rc = _run(["live-domains", "--instance", "i", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = [ln for ln in out.splitlines() if ln.startswith(("tdd ", "sleep "))]
    first = lines[: lines.index("tdd domain delete-model --domain i_world") + 2]
    # a live call runs as written: nothing is filled in from the domains stage
    assert first[0] == "tdd domain create-data --domain i_world"
    assert first[1:4] == [
        "sleep 1",
        "tdd domain modify-data --domain i_world --entity city --ops Insert",
        "tdd domain modify-data --domain i_fs",
    ]
    assert first[4] == "sleep 1"  # the inner loop's next pass
    assert first[-3:] == [
        "tdd domain delete-data --domain i_world",
        "tdd domain delete-model --domain i_world",
        "tdd domain create-model --domain i_world --force --model world",
    ]
    assert len([ln for ln in lines if ln.startswith("tdd ")]) == 3 * 24
    # each call is a step, labelled with the entries and passes it is under
    assert "cycle 1/3 > churn 10/10 > city" in err


def test_dry_run_marks_what_goes_to_the_background_and_what_waits(xp_root, capsys):
    _live_suite(
        xp_root,
        [
            {"name": "seed", "domain": _dom("world", "create-data")},
            {
                "name": "churn",
                "blocking": False,
                "repeat": 2,
                "live": [
                    {"name": "change", "domain": _dom("world", "modify-data")},
                ],
            },
            {"name": "settle", "wait": ["churn"]},
            {"name": "reset", "domain": _dom("world", "delete-data")},
        ],
    )
    _instance(xp_root)
    capsys.readouterr()
    rc = _run(["live-domains", "--instance", "i", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert out.splitlines()[:7] == [
        "tdd domain create-data --domain i_world",
        "# churn: starts in the background",
        "tdd domain modify-data --domain i_world",
        "tdd domain modify-data --domain i_world",
        "# churn: ends",
        "# settle: wait for churn",
        "tdd domain delete-data --domain i_world",
    ]


def test_a_non_blocking_entry_runs_side_by_side_until_waited_for(xp_root, monkeypatch):
    """`churn` starts and the script goes on: `seed`, after it, runs while
    churn is still inside its call -- churn only finishes once seed has run, so
    a churn that held the script would never finish. `reset` waits for it."""
    import threading

    from tabsdata_dev.tool.xp import live

    seeded = threading.Event()
    order: list[str] = []

    def call(argv, action, path, where):
        if where == "churn":
            assert seeded.wait(5), "churn held the script"
        if where == "seed":
            seeded.set()
        order.append(where)

    monkeypatch.setattr(live, "_call", call)
    inst = _live_instance(
        xp_root,
        [
            {
                "name": "churn",
                "blocking": False,
                "domain": _dom("world", "modify-data"),
            },
            {"name": "seed", "domain": _dom("world", "create-data")},
            {"name": "settle", "wait": ["churn"]},
            {"name": "reset", "domain": _dom("world", "delete-data")},
        ],
    )
    live.run_script(inst)
    assert order == ["seed", "churn", "reset"]


def test_a_repeat_pass_ends_when_everything_it_started_has(xp_root, monkeypatch):
    """A background entry inside a pass is waited for at the end of the pass:
    pass 2 does not start while pass 1's background call still runs."""
    import threading
    import time

    from tabsdata_dev.tool.xp import live

    lock = threading.Lock()
    events: list[str] = []

    def call(argv, action, path, where):
        with lock:
            events.append(f"start {where}")
        if where.endswith("slow"):
            time.sleep(0.1)
        with lock:
            events.append(f"end {where}")

    monkeypatch.setattr(live, "_call", call)
    inst = _live_instance(
        xp_root,
        [
            {
                "name": "g",
                "repeat": 2,
                "live": [
                    {
                        "name": "slow",
                        "blocking": False,
                        "domain": _dom("world", "modify-data"),
                    },
                    {"name": "quick", "domain": _dom("fs", "modify-data")},
                ],
            },
        ],
    )
    live.run_script(inst)
    assert events.index("end g 1/2 > slow") < events.index("start g 2/2 > slow")


def test_a_failed_background_entry_stops_the_script_and_is_its_error(
    xp_root, monkeypatch
):
    """The first failure anywhere is the run's: what still runs stops at its
    next step or pause, and nothing after it starts."""
    from tabsdata_dev.tool.xp import live, state

    calls: list[str] = []

    def call(argv, action, path, where):
        calls.append(where)
        if where == "bad":
            state.die("bad entry failed")

    monkeypatch.setattr(live, "_call", call)
    inst = _live_instance(
        xp_root,
        [
            {
                "name": "slow",
                "blocking": False,
                "repeat": 50,
                "live": [
                    {"name": "nap", "sleep": "0.05s"},
                    {"name": "tick", "domain": _dom("world", "modify-data")},
                ],
            },
            {"name": "bad", "blocking": False, "domain": _dom("fs", "modify-data")},
            {"name": "settle", "wait": ["bad"]},
            {"name": "after", "domain": _dom("world", "delete-data")},
        ],
    )
    with pytest.raises(state.XpError, match="bad entry failed"):
        live.run_script(inst)
    assert "after" not in calls
    assert len([c for c in calls if c.startswith("slow")]) < 50


def test_one_shot_runs_the_live_script_after_the_triggers_unless_told_not_to(
    xp_root, capsys
):
    _live_suite(xp_root, [{"name": "b", "domain": _dom("world", "modify-data")}])

    def lines(*extra):
        rc = _run(
            [
                "one-shot",
                "--suite",
                "live/one",
                *_suites_dir(xp_root),
                "--project",
                "p",
                "--dry-run",
                *extra,
            ]
        )
        out, err = capsys.readouterr()
        assert rc == 0, err
        return [ln for ln in out.splitlines() if ln.startswith("tdd ")]

    ran = lines()
    live_at = ran.index("tdd domain modify-data --domain p_world")
    monitors = [i for i, ln in enumerate(ran) if ln.startswith("tdd tdk trx list")]
    # watched once for the triggers, then again for what the changes started
    assert monitors[0] < live_at < monitors[1]
    assert "tdd domain modify-data --domain p_world" not in lines("--no-live")


STAGED = [
    {"_comment": "a comment entry reads as nothing"},
    {"domains": calls("world", "fs", "world", 10)},
    {
        "live": [
            {"name": "early", "domain": _dom("world", "modify-data", "--ops", "Insert")}
        ]
    },
    {
        "collections": [
            {
                "name": "src",
                "type": "local_file_in",
                "connection_template": "connection-file:connections/local_file_in.yaml",
                "group": "sources",
                "domains": {"D0": "world"},
            }
        ]
    },
    {
        "functions": [
            {
                "collection": "src",
                "functionpath": "functions/f.py::pub",
                "enabled": False,
            }
        ]
    },
    {"domains": calls("fs", "fs")},
    {"triggers": [{"collection": "src", "function": "pub", "detached": True}]},
    {"monitor": True},
]


def _staged_suite(xp_root, doc=STAGED):
    path = xp_root / "suites" / "staged" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc))
    return path


def test_a_suite_is_an_ordered_list_of_stages(xp_root):
    from tabsdata_dev.tool.xp import suites
    from tabsdata_dev.tool.xp.models import build_instance

    path = _staged_suite(xp_root)
    assert suites.is_suite_def(path)
    inst = build_instance("i", path)
    assert [s.kind for s in inst.stages] == [
        "domains",
        "live",
        "collections",
        "functions",
        "domains",
        "triggers",
        "monitor",
    ]
    # every entry of a kind, across its stages, for the phase verbs
    assert [d.name for d in inst.domains] == ["world", "fs"]
    assert inst.functions[0].enabled is False


def test_the_older_single_object_is_refused_naming_the_list_it_ran(xp_root, capsys):
    """Recognised, so a suite dir holding one fails loudly and list-suites
    marks it -- never read as a suite."""
    from tabsdata_dev.tool.xp import state, suites
    from tabsdata_dev.tool.xp.models import build_instance

    path = _staged_suite(xp_root, SUITE)
    assert suites.is_suite_def(path)
    with pytest.raises(
        state.XpError,
        match='a single object, a form xp no longer reads.*"monitor": true',
    ):
        build_instance("i", path)
    assert _run(["list-suites", *_suites_dir(xp_root)]) == 0
    out = capsys.readouterr().out
    assert "staged/one" in out and "single object: no longer read" in out


@pytest.mark.parametrize(
    "doc, why",
    [
        ("nope", "must be a JSON list of stages"),
        (["nope"], "stage 1 is not a JSON object"),
        (
            [{"domains": [], "triggers": []}],
            "exactly one of .* \\(has domains, triggers\\)",
        ),
        ([{"deploy": []}], "exactly one of"),
        ([{"monitor": 5}], "monitor takes true"),
        ([{"domains": {}}], "domains takes a list"),
        (
            [
                {
                    "collections": [
                        {"name": "c", "type": "t", "group": "g", "domains": {"D0": "d"}}
                    ]
                },
                {"domains": calls("d", "fs")},
            ],
            "collection 'c' names domain 'd', created by a later stage",
        ),
        (
            [
                {
                    "functions": [
                        {"collection": "c", "functionpath": "functions/f.py::x"}
                    ]
                },
                {"collections": [{"name": "c", "type": "t", "group": "g"}]},
            ],
            "in collection 'c', created by a later stage",
        ),
        (
            [
                {"live": [{"name": "x", "domain": _dom("d", "delete-data")}]},
                {"domains": calls("d", "fs")},
            ],
            "live entry 'x' names domain 'd', created by a later stage",
        ),
    ],
)
def test_a_list_suite_is_refused_when_it_is_read(xp_root, doc, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, doc))


def test_run_suite_runs_the_stages_in_the_order_listed(xp_root, capsys):
    _staged_suite(xp_root)
    rc = _run(
        [
            "create-instance",
            "--suite",
            "staged/one",
            *_suites_dir(xp_root),
            "--instance",
            "i",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    rc = _run(["run-suite", "--instance", "i", "--project", "p", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = [ln for ln in out.splitlines() if ln.startswith("tdd ")]

    def at(prefix):
        return next(i for i, ln in enumerate(lines) if ln.startswith(prefix))

    order = [
        at("tdd domain create --domain i_world --sys fs"),  # stage 1: world
        at(
            "tdd domain modify-data --domain i_world --ops Insert"
        ),  # live, before the project
        at("tdd tdk project create --name p"),  # the first project stage creates it
        at("tdd tdk collection create --proj p --name src"),
        at("tdd tdk fn register --update --proj p --coll src"),
        at("tdd tdk fn trigger --proj p --coll src --name pub"),
        at("tdd tdk trx list --proj p --monitor"),
    ]
    assert order == sorted(order)
    # the second domains stage runs where it stands, between them
    assert order[4] < at("tdd domain create --domain i_fs --sys fs") < order[5]
    # "enabled": false registers it disabled
    assert lines[order[4]].endswith(" --disabled")


def test_a_live_stages_background_entries_run_through_later_stages(
    xp_root, monkeypatch
):
    """A live stage returns with its non-blocking entries still running; a
    later live stage waits for them by name; the suite's end waits for the
    rest."""
    import threading

    from tabsdata_dev.tool.xp import live
    from tabsdata_dev.tool.xp.models import build_instance

    released = threading.Event()
    done: list[str] = []

    def call(argv, action, path, where):
        if where == "bg":
            assert released.wait(5)
        done.append(where)

    monkeypatch.setattr(live, "_call", call)
    doc = [
        {"domains": calls("world", "fs")},
        {
            "live": [
                {
                    "name": "bg",
                    "blocking": False,
                    "domain": _dom("world", "modify-data"),
                }
            ]
        },
        {
            "live": [
                {"name": "settle", "wait": ["bg"]},
                {"name": "after", "domain": _dom("world", "delete-data")},
            ]
        },
    ]
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    inst = build_instance("i", _staged_suite(xp_root, doc))
    session = live.Session(inst)
    session.stage(inst.stages[1].live)  # returns while bg still runs
    assert done == []
    released.set()  # a stage in between, running beside it
    session.stage(inst.stages[2].live)
    session.finish()
    assert done == ["bg", "after"]


@pytest.mark.parametrize(
    "value, seconds",
    [("90s", 90.0), ("2m", 120.0), ("1.5h", 5400.0), (" 3 s ", 3.0), ("0s", 0.0)],
)
def test_a_duration_is_a_value_and_a_unit(value, seconds):
    from tabsdata_dev.tool.xp.models import seconds_of

    assert seconds_of(value, "x") == seconds


@pytest.mark.parametrize("value", ["5", 5, 0.5, "5x", "m", "-1s", True, None])
def test_a_duration_without_a_known_unit_is_refused(value):
    from tabsdata_dev.tool.xp.models import seconds_of

    with pytest.raises(ValueError, match="x"):
        seconds_of(value, "x")


def _sentinel_suite(**over):
    entry = {
        "collection": "c",
        "table": "xp_sentinel_changes",
        "wait_for_key": "k",
        "time_out": "5m",
        **over,
    }
    return [
        {"collections": [{"name": "c", "type": "t", "group": "g"}]},
        {"live": [{"name": "settle", "sleep": "2m"}]},
        {"sentinel": [entry]},
    ]


def test_a_sentinel_stage_reads_and_sleep_takes_a_unit(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", _staged_suite(xp_root, _sentinel_suite()))
    assert [s.kind for s in inst.stages] == ["collections", "live", "sentinel"]
    assert inst.live[0].sleep_seconds == 120.0
    [s] = inst.stages[2].sentinel
    assert (s.collection, s.table, s.wait_for_key, s.seconds) == (
        "c",
        "xp_sentinel_changes",
        "k",
        300.0,
    )


@pytest.mark.parametrize(
    "doc, why",
    [
        (_sentinel_suite(time_out="soon"), "time_out: 'soon' is not <VALUE><UNIT>"),
        (_sentinel_suite(key="k"), "Extra inputs are not permitted"),
        (
            [_sentinel_suite()[2], _sentinel_suite()[0]],
            "sentinel 'k' reads collection 'c', created by a later stage",
        ),
        (
            [{"live": [{"name": "x", "sleep": "soon"}]}],
            "sleep: 'soon' is not <VALUE><UNIT>",
        ),
        (
            [{"live": [{"name": "x", "sleep": 30}]}],
            "sleep: 30 is not <VALUE><UNIT>",
        ),
        (
            [{"live": [{"name": "x", "sleep_secs": 30}]}],
            "sleep_secs\n  Extra inputs are not permitted",
        ),
    ],
)
def test_a_bad_sentinel_or_duration_is_refused_when_read(xp_root, doc, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, doc))


def test_a_sentinel_reads_every_version_once_until_one_holds_the_key(
    xp_root, monkeypatch
):
    """Each flush of a stream is a version of its own, so every version is
    read -- once, since a committed one never changes; one that cannot be read
    yet is tried again. The latch opens on the version holding the key."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, shell, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(project.time, "sleep", lambda s: None)
    looks = iter(
        [[{"id": "v1"}, {"id": "v2"}], [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}]]
    )
    reads: list[str] = []
    unreadable = {"v2"}

    def tdk(args, want_json=True, check=True, stdin_text=None):
        if args[:2] == ["table", "versions"]:
            assert "--max-result" in args and "xp_sentinel_changes" in args
            return next(looks)
        vid = args[args.index("--version") + 1]
        reads.append(vid)
        sql = args[args.index("--sql") + 1]
        assert sql.endswith("WHERE sentinel_key = 'it''s'")
        if vid in unreadable:
            unreadable.discard(vid)
            return None
        return [{"sentinel_key": "it's"}] if vid == "v3" else []

    monkeypatch.setattr(shell, "tdk", tdk)
    s = Sentinel(
        collection="c", table="xp_sentinel_changes", wait_for_key="it's", time_out="1m"
    )
    project.wait_sentinels("p", [s])
    assert reads == ["v1", "v2", "v2", "v3"]


def test_a_sentinel_that_never_arrives_fails_at_its_time_out(xp_root, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, shell, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(
        shell,
        "tdk",
        lambda args, **kw: [{"id": "v1"}] if args[1] == "versions" else [],
    )
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="0s")
    with pytest.raises(
        state.XpError, match="sentinel 'k' not in any version of c/t after 0s"
    ):
        project.wait_sentinels("p", [s])


def test_run_suite_dry_run_shows_the_sentinel_after_the_stages_before_it(
    xp_root, capsys
):
    doc = [
        *STAGED,
        {
            "sentinel": [
                {
                    "collection": "src",
                    "table": "xp_sentinel_changes",
                    "wait_for_key": "k",
                    "time_out": "90s",
                }
            ]
        },
    ]
    _staged_suite(xp_root, doc)
    rc = _run(
        [
            "create-instance",
            "--suite",
            "staged/one",
            *_suites_dir(xp_root),
            "--instance",
            "i",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    rc = _run(["run-suite", "--instance", "i", "--project", "p", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = out.splitlines()
    monitor = next(
        i for i, ln in enumerate(lines) if "trx list --proj p --monitor" in ln
    )
    versions = next(i for i, ln in enumerate(lines) if "table versions" in ln)
    assert monitor < versions
    assert "--coll src --name xp_sentinel_changes --max-result 0" in lines[versions]
    assert any("until 'k' is in one, at most 90s" in ln for ln in lines)


def _script(xp_root, body: str, name: str = "check.py") -> str:
    path = xp_root / "suites" / "staged" / "scripts" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body)
    return f"scripts/{name}"


def test_the_work_dir_tokens_expand_at_use_and_unknown_ones_are_refused(xp_root):
    """${XP_WORK_DIR} is the run's <scratch>/work, made on first use;
    ${XP_PROJECT} needs a project; any other ${XP_*} is a typo, refused when
    the suite is read."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state, work
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    expanded = work.expand("${XP_WORK_DIR}/ops.jsonl")
    assert expanded == f"{work.work_dir()}/ops.jsonl" and work.work_dir().is_dir()
    assert work.expand("p=${XP_PROJECT}", "proj") == "p=proj"
    with pytest.raises(state.XpError, match=r"\$\{XP_PROJECT\} has no value here"):
        work.expand("${XP_PROJECT}")
    doc = [{"domains": calls("d", "fs", "world", 1, "--emit-ops", "${XP_WORKDIR}/x")}]
    with pytest.raises(state.XpError, match=r"\$\{XP_WORKDIR\} is not a token"):
        build_instance("i", _staged_suite(xp_root, doc))


def test_a_domain_call_expands_its_tokens_and_a_create_gets_its_backend_name(
    xp_root,
):
    """A domains stage's calls run as written, tokens expanded; a create also
    gets the per-run --name-in-system, which a suite may not set itself."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import domains, state, work
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    doc = [
        {
            "domains": calls(
                "d", "fs", "world", 1, "--emit-ops", "${XP_WORK_DIR}/ops.jsonl"
            )
        }
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    create, model, data = inst.stages[0].domains
    assert [d.name for d in inst.domains] == ["d"] and inst.domains[0].system == "fs"
    argv = domains.call_argv(inst, create)
    assert argv[-6:-2] == ["--domain", "i_d", "--sys", "fs"]
    assert argv[-2] == "--name-in-system" and argv[-1].endswith("_d")
    assert domains.call_argv(inst, data)[-2:] == [
        "--emit-ops",
        f"{work.work_dir()}/ops.jsonl",
    ]
    assert "--name-in-system" not in domains.call_argv(inst, model)


@pytest.mark.parametrize(
    "doc, why",
    [
        (
            [{"domains": [{"name": "d", "command": "create", "options": []}]}],
            "needs --sys",
        ),
        (
            [
                {
                    "domains": [
                        {
                            "name": "d",
                            "command": "create-data",
                            "options": ["--size", "1"],
                        }
                    ]
                }
            ],
            "create-data on 'd' before any create of it",
        ),
        ([{"domains": calls("d", "fs") + calls("d", "fs")}], "'d' is created twice"),
        (
            [
                {
                    "domains": [
                        {
                            "name": "d",
                            "command": "create",
                            "options": ["--sys", "fs", "--name-in-system", "x"],
                        }
                    ]
                }
            ],
            "options set by xp itself: --name-in-system",
        ),
        (
            [{"domains": [{"name": "d", "command": "destroy", "options": []}]}],
            "domains command 'destroy' is not one of",
        ),
        (
            [{"domains": [{"name": "d", "system": "fs"}]}],
            "Field required",
        ),
    ],
)
def test_a_bad_domain_call_is_refused_when_read(xp_root, doc, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, doc))


@pytest.mark.parametrize(
    "entry, why",
    [
        (
            {"name": "x", "py_script": "/abs/check.py"},
            "must be a .py path inside the suite",
        ),
        (
            {"name": "x", "py_script": "../check.py"},
            "must be a .py path inside the suite",
        ),
        (
            {"name": "x", "py_script": "scripts/missing.py"},
            "no script 'scripts/missing.py'",
        ),
        ({"name": "x", "py_script": "scripts/check.py", "retries": 2}, "Extra inputs"),
        (
            {"name": "x", "py_script": "scripts/check.py", "params": ["${XP_NOPE}"]},
            r"\$\{XP_NOPE\} is not a token",
        ),
    ],
)
def test_a_bad_execute_entry_is_refused_when_read(xp_root, entry, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    _script(xp_root, "import sys; sys.exit(0)\n")
    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, [{"execute": [entry]}]))


def _execute_suite(xp_root, entries):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    return build_instance("i", _staged_suite(xp_root, [{"execute": entries}]))


@pytest.fixture
def launcher(monkeypatch, xp_root):
    """`tdd-exe` stood in for: `_xp-execute SCRIPT ARGS` runs the script on this
    python, as the launcher does; every other tool is not expected here."""
    import sys

    from tabsdata_dev.tool.xp import execute

    monkeypatch.setenv("TDD_DIR", str(xp_root.parent / "tdd"))

    def tool_argv(name, *args):
        if name == "_xp-execute":
            return [sys.executable, *args]
        return ["/fake/tdd/bin/tdd-exe", name, *args]

    monkeypatch.setattr(execute.proc, "tool_argv", tool_argv)
    return execute


def test_an_execute_script_gets_its_params_env_and_path(xp_root, launcher):
    """Run by `tdd _xp-execute` from the suite dir, params expanded, the run's
    names in its environment and tdd-exe first on its PATH."""
    from tabsdata_dev.tool.xp import work

    out = xp_root / "seen.json"
    _script(
        xp_root,
        "import json, os, sys\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'env': {k: os.environ[k] for k in ('XP_WORK_DIR', 'XP_PROJECT', 'XP_INSTANCE')}, "
        "'venv': os.environ.get('_TDD_XP_EXECUTE_VENV'), "
        f"'path0': os.environ['PATH'].split(os.pathsep)[0]}}, open({str(out)!r}, 'w'))\n",
    )
    inst = _execute_suite(
        xp_root,
        [
            {
                "name": "c",
                "py_script": "scripts/check.py",
                "params": ["${XP_WORK_DIR}/ops.jsonl", "${XP_PROJECT}"],
            }
        ],
    )
    assert launcher.run_scripts(inst, "proj", inst.stages[0].execute) == 0
    seen = json.loads(out.read_text())
    assert seen["argv"] == [f"{work.work_dir()}/ops.jsonl", "proj"]
    assert (
        pathlib.Path(seen["cwd"]).resolve() == pathlib.Path(inst.source_dir).resolve()
    )
    assert seen["env"] == {
        "XP_WORK_DIR": str(work.work_dir()),
        "XP_PROJECT": "proj",
        "XP_INSTANCE": "i",
    }
    assert seen["path0"] == "/fake/tdd/bin" and seen["venv"] is None


def test_a_failed_script_stops_the_run_unless_it_continues_on_fail(xp_root, launcher):
    from tabsdata_dev.tool.xp import state

    _script(xp_root, "print('row 3 differs'); raise SystemExit(1)\n", "bad.py")
    _script(xp_root, "raise SystemExit(0)\n", "good.py")
    bad = {"name": "bad", "py_script": "scripts/bad.py"}
    good = {"name": "good", "py_script": "scripts/good.py"}

    inst = _execute_suite(xp_root, [{**bad, "continue_on_fail": True}, good])
    assert launcher.run_scripts(inst, "p", inst.stages[0].execute) == 1  # deferred
    steps = [(s["path"], s["ok"]) for s in state.run.reporter.steps]
    assert steps[-2:] == [("bad", False), ("good", True)]  # the next one still ran

    inst = _execute_suite(xp_root, [bad, good])
    with pytest.raises(state.XpError, match="(?s)execute 'bad' failed.*row 3 differs"):
        launcher.run_scripts(inst, "p", inst.stages[0].execute)


def test_requirements_get_a_one_off_venv_deleted_whether_the_script_passes_or_not(
    xp_root, launcher, monkeypatch
):
    """The venv is made, named to the launcher in _TDD_XP_EXECUTE_VENV, and
    deleted after the step -- also when the script fails. Its name starts
    tdd-xp-execute-, what a clean-up after a killed run looks for."""
    from tabsdata_dev.tool.xp import state

    made, deleted = [], []

    def one_off_venv(inst, e):
        name = launcher.venv_name(inst, e)
        made.append((name, [r.spec for r in e.requirements]))
        return name, xp_root / "venvs" / name

    monkeypatch.setattr(launcher, "one_off_venv", one_off_venv)
    monkeypatch.setattr(launcher, "delete_venv", deleted.append)
    out = xp_root / "venv.txt"
    _script(
        xp_root,
        f"import os, sys; open({str(out)!r}, 'w').write(os.environ['_TDD_XP_EXECUTE_VENV']); "
        "sys.exit(int(sys.argv[1]))\n",
    )
    entry = {
        "name": "needs",
        "py_script": "scripts/check.py",
        "requirements": [{"name": "polars", "version": "1.44.1"}, {"name": "rich"}],
    }
    for status, passed in (("0", True), ("1", False)):
        inst = _execute_suite(
            xp_root, [{**entry, "params": [status], "continue_on_fail": True}]
        )
        assert launcher.run_scripts(inst, "p", inst.stages[0].execute) == (
            0 if passed else 1
        )
    assert [m[1] for m in made] == [["polars==1.44.1", "rich"]] * 2
    assert deleted == [m[0] for m in made]  # both, the failed one too
    assert all(m[0].startswith("tdd-xp-execute-") for m in made)
    assert out.read_text().endswith(made[-1][0])

    # a venv that cannot be made fails the step, and nothing is left to delete
    deleted.clear()

    def cannot(inst, e):
        raise state.XpError("one-off venv x failed: no uv")

    monkeypatch.setattr(launcher, "one_off_venv", cannot)
    inst = _execute_suite(xp_root, [entry])
    with pytest.raises(state.XpError, match="no uv"):
        launcher.run_scripts(inst, "p", inst.stages[0].execute)
    assert deleted == []


@pytest.mark.parametrize(
    "req, why",
    [
        ({"name": "polars", "version": ">=1"}, "is an exact version"),
        ({"name": "bad name"}, "is not a package name"),
        ({"name": "polars", "pin": "1"}, "Extra inputs"),
    ],
)
def test_a_bad_requirement_is_refused_when_read(xp_root, req, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    _script(xp_root, "pass\n")
    entry = {"name": "x", "py_script": "scripts/check.py", "requirements": [req]}
    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, [{"execute": [entry]}]))


def test_enable_and_disable_a_registered_function(xp_root, capsys):
    from tabsdata_dev.tool.xp import pointers

    for verb in ("enable", "disable"):
        rc = _run(
            [
                f"{verb}-function",
                "--project",
                "p",
                "--collection",
                "src",
                "--function",
                "pub",
                "--dry-run",
                "--profile",
                "sm_a",
            ]
        )
        out, err = capsys.readouterr()
        assert rc == 0, err
        assert f"tdd tdk fn {verb} --proj p --coll src --name pub --profile sm_a" in out
    pointers.write_group_project("g", ["g_a", "g_b"])
    rc = _run(
        ["enable-function", "--project", "g", "--collection", "c", "--function", "f"]
    )
    assert rc == 1 and "is a group" in capsys.readouterr().err


def test_every_built_in_suite_reads(tmp_path, monkeypatch):
    """Both forms -- the list of stages and the older single object -- across
    every definition the package carries: a suite that no longer validates is
    found here, not by the run that picks it."""
    from tabsdata_dev.tool.xp import suites
    from tabsdata_dev.tool.xp.models import build_instance

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    root = suites.builtin_root() / "suites"
    files = [
        f for d in sorted(root.iterdir()) if d.is_dir() for f in suites.lane_files(d)
    ]
    assert len(files) > 100
    for f in files:
        assert build_instance("i", f).stages, f
    staged = build_instance(
        "i", root / "container-connectors" / "postgrescdc_initial_load_live.json"
    )
    assert [s.kind for s in staged.stages] == [
        "domain-manifest",
        "live",
        "collections",
        "functions",
        "live",
        "sentinel",
        "monitor",
    ]


def _dm(*domains, emit_ops=None):
    body = {"domains": list(domains)}
    if emit_ops is not None:
        body = {"emit_ops": emit_ops, **body}
    return {"domain-manifest": body}


PG = {"name": "pg", "system": "postgres", "model": "world", "data": "s"}
FS = {"name": "fs", "system": "fs"}


def test_a_domain_manifest_stage_reads_its_domains_and_emit_settings(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    doc = [
        _dm(PG, FS, {**PG, "name": "quiet", "emit": False}, emit_ops="${XP_WORK_DIR}/o")
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    [stage] = inst.stages
    assert stage.kind == "domain-manifest"
    assert [(d.name, d.system) for d in inst.domains] == [
        ("pg", "postgres"),
        ("fs", "fs"),
        ("quiet", "postgres"),
    ]
    dm = stage.domain_manifest
    assert dm.emit_ops == "${XP_WORK_DIR}/o" and [d.emit for d in dm.domains] == [
        True,
        True,
        False,
    ]
    assert dm.domains[0].size == 10


@pytest.mark.parametrize(
    "doc, why",
    [
        ([{"domain-manifest": [PG]}], "domain-manifest takes an object"),
        ([_dm({**PG, "data": "huge"})], "data 'huge' is not one of"),
        ([_dm({"name": "x", "system": "fs", "data": "xs"})], "data needs a model"),
        ([_dm(PG, emit_ops="${XP_WORKDIR}/o")], r"\$\{XP_WORKDIR\} is not a token"),
        ([_dm({**PG, "name_in_system": "pinned"})], "Extra inputs"),
        ([_dm(PG), {"domains": calls("pg", "fs")}], "'pg' is created twice"),
        ([{"domain-manifest": {"domains": []}}], "names no domains"),
    ],
)
def test_a_bad_domain_manifest_is_refused_when_read(xp_root, doc, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, doc))


def test_a_domain_manifest_seeds_to_files_of_their_own_then_joins_them_in_order(
    xp_root, monkeypatch
):
    """Only a seeded domain whose emit is not false gets an emit-ops file, each
    its own (the batch loads them side by side); once the batch is done they
    are appended to emit_ops in the order listed, whatever order they finished
    in -- appended, since live calls keep adding to the same trail."""
    import yaml

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import domains, shell, state, work
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(shell, "stored_domains", lambda: set())
    seen: dict = {}

    def run_manifest(verb, manifest, names, extra):
        entries = yaml.safe_load(manifest.read_text())
        seen["entries"] = entries
        for e in reversed(entries):  # finish in the other order
            if "emit-ops" in e:
                pathlib.Path(e["emit-ops"]).write_text(f"{e['name']}\n")

    monkeypatch.setattr(domains, "run_manifest", run_manifest)
    doc = [
        _dm(
            PG,
            FS,
            {**PG, "name": "quiet", "emit": False},
            {**PG, "name": "pg2"},
            emit_ops="${XP_WORK_DIR}/ops.jsonl",
        )
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    final = work.work_dir() / "ops.jsonl"
    final.write_text("earlier\n")
    domains.create_from_manifest(inst, inst.stages[0].domain_manifest, 1)
    by = {e["name"]: e for e in seen["entries"]}
    assert set(by) == {"i_pg", "i_fs", "i_quiet", "i_pg2"}
    assert "emit-ops" not in by["i_fs"] and "emit-ops" not in by["i_quiet"]
    assert by["i_pg"]["emit-ops"] != by["i_pg2"]["emit-ops"]  # one file each
    assert by["i_pg"]["size"] == 10 and by["i_pg"]["name-in-system"].endswith("_pg")
    assert final.read_text() == "earlier\ni_pg\ni_pg2\n"


def test_a_domain_manifest_without_emit_ops_captures_nothing(xp_root, monkeypatch):
    import yaml

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import domains, shell, state
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(shell, "stored_domains", lambda: set())
    seen: list = []
    monkeypatch.setattr(
        domains,
        "run_manifest",
        lambda verb, manifest, names, extra: seen.extend(
            yaml.safe_load(manifest.read_text())
        ),
    )
    inst = build_instance("i", _staged_suite(xp_root, [_dm(PG)]))
    domains.create_from_manifest(inst, inst.stages[0].domain_manifest, 1)
    assert [e["name"] for e in seen] == ["i_pg"] and "emit-ops" not in seen[0]


def test_list_suites_counts_domains_of_both_stage_kinds():
    """Domains, not calls: a domain-manifest's entries and a domains stage's
    creates -- every built-in suite showed domains=0 once they moved to
    domain-manifest."""
    from tabsdata_dev.tool.xp import suites

    doc = [
        _dm(PG, FS),
        {"domains": calls("x", "fs", "world", 1)},  # 3 calls, one domain
        {"collections": [{"name": "c", "type": "t", "group": "g"}]},
    ]
    assert suites._count(doc, "domains") == 3
    assert suites._count(doc, "collections") == 1
