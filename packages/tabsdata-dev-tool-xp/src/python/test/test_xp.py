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
        line.startswith("demo/one - [1/2] - create-domain") for line in err.splitlines()
    )
    assert out.splitlines()[-1].startswith("demo/one - summary - 2 step(s), all ok")


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
                    {"name": "pause", "sleep_secs": 1},
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
            {"name": "model", "domain": _dom("world", "create-model", "--force")},
        ],
    }
]


def _live_suite(xp_root, live=LIVE):
    path = xp_root / "suites" / "live" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({**SUITE, "live": live}))
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
        ([{"name": "1st", "sleep_secs": 1}], "a letter"),
        ([{"name": "x"}], "exactly one of 'domain', 'sleep_secs', 'wait' or 'live'"),
        (
            [{"name": "x", "sleep_secs": 1, "wait": ["y"]}],
            "exactly one of .* \\(has sleep_secs, wait\\)",
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
            [{"name": "x", "sleep_secs": 1, "blocking": False}],
            "only a 'domain' or 'live' entry",
        ),
        (
            [{"name": "x", "repeat": 2, "domain": _dom("world", "delete-data")}],
            "'repeat' goes with 'live'",
        ),
        ([{"name": "x", "repeat": 0, "live": []}], "repeat must be >= 1"),
        (
            [
                {"name": "x", "sleep_secs": 1},
                {"name": "x", "sleep_secs": 1},
            ],
            "'x' is used twice",
        ),
        (
            [{"name": "w", "wait": ["later"]}, {"name": "later", "sleep_secs": 1}],
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
            [{"name": "s", "sleep_secs": 1}, {"name": "w", "wait": ["s"]}],
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
    # create-data takes the size the suite declares (s = x10), create-model its model
    assert first[0] == "tdd domain create-data --domain i_world --size 10"
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
        "tdd domain create-data --domain i_world --size 10",
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
                    {"name": "nap", "sleep_secs": 0.05},
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
    {"domains": [{"name": "world", "system": "fs", "model": "world", "data": "s"}]},
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
    {"domains": [{"name": "fs", "system": "fs"}]},
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


def test_the_older_single_object_reads_as_the_stages_it_always_ran(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", xp_root / "suites" / "demo" / "one.json")
    assert [s.kind for s in inst.stages] == [
        "domains",
        "collections",
        "functions",
        "triggers",
        "monitor",
    ]
    live = {**SUITE, "live": [{"name": "b", "domain": _dom("world", "delete-data")}]}
    inst = build_instance("i", _staged_suite(xp_root, live))
    assert [s.kind for s in inst.stages][-2:] == ["live", "monitor"]


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
                {"domains": [{"name": "d", "system": "fs"}]},
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
                {"domains": [{"name": "d", "system": "fs"}]},
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
        at("tdd domain create --manifest"),  # stage 1: world
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
    # the second domains stage has a manifest of its own, between them
    manifests = [
        i for i, ln in enumerate(lines) if ln.startswith("tdd domain create --manifest")
    ]
    assert len(manifests) == 2 and order[4] < manifests[1] < order[5]
    assert "domains-6.yaml" in lines[manifests[1]]
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
        {"domains": [{"name": "world", "system": "fs"}]},
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
