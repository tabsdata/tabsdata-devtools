#
# Copyright 2026 Tabsdata Inc.
#

import json
import re
import pathlib

import pytest

#: The suite run's IDs under the fixture's clock and build identity: the first
#: run a test makes; each next one is a second on.
XP_ID = "xp_tucu_0_20261001T093012"
XP_SHORT = "tuc00_0e2aec"
#: What a suite read with no run behind it (`build_instance` without IDs) names
#: its own domains by.
PH = "xp_user_0_20260101T000000"


MONITOR = {"monitor": {"time_out": "30m"}}


def N(name):
    """A suite's own domain, as a suite names it: `<XP_ID>_<name>` once read."""
    return "${xp:name(%s)}" % name


def calls(name, system, model=None, size=None, *data_opts):
    """A domain as a domains stage writes it: its create and, seeded, its
    create-model and create-data."""
    name = N(name)
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
            "domains": {"D0": N("world")},
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
    return stages + [MONITOR]


@pytest.fixture
def xp_root(tmp_path, monkeypatch):
    root = tmp_path / "xp"
    (root / "suites" / "demo" / "functions").mkdir(parents=True)
    (root / "connections").mkdir()
    (root / "suites" / "demo" / "one.json").write_text(json.dumps(_stages(SUITE)))
    (root / "suites" / "demo" / "two.json").write_text(json.dumps([MONITOR]))
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
    _run_the_clock(monkeypatch)
    return root


def _run_the_clock(monkeypatch):
    """Run IDs from a clock the test owns: XP_ID first, a second on each next."""
    from datetime import datetime, timezone

    from tabsdata_dev.tool.xp import ids

    monkeypatch.setenv("TD_BUILD_USER", "tucu")
    monkeypatch.setenv("TD_BUILD_NUMBER", "0")
    now = [datetime(2026, 10, 1, 9, 30, 12, tzinfo=timezone.utc).timestamp()]
    monkeypatch.setattr(ids, "clock", lambda: now[0])
    monkeypatch.setattr(ids, "sleep", lambda s: now.__setitem__(0, now[0] + max(s, 0)))
    monkeypatch.setattr(ids, "_last", -1)


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
    pointers.write_instance("i1", one, (XP_ID, XP_SHORT))
    assert pointers.store() == tmp_path / "tdd" / "data" / "xp"
    inst = pointers.load_instance("i1")
    assert (
        inst.suite_file == str(one)
        and inst.base_dir == str(xp_root)
        and inst.type == "demo"
    )
    # the suite read for the run the pointer holds: its domains are the run's
    assert [d.name for d in inst.domains] == [f"{XP_ID}_fs", f"{XP_ID}_world"]
    assert pointers.ids_of("i1") == (XP_ID, XP_SHORT)
    pointers.write_project("p1", "i1")
    assert (
        pointers.load_project("p1") == "i1"
        and pointers.suite_of_project("p1") == "demo/one"
    )
    pointers.write_group_instance(
        "g", ["g_one", "g_two"], one.parent, (XP_ID, XP_SHORT)
    )
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


def test_a_runs_domain_is_named_by_its_ids_and_a_fixed_one_as_written(xp_root):
    """`${xp:name(x)}` is the run's domain, `<XP_ID>_x` in the store and
    `<XP_SHORT_ID>_x` in the system -- short, because a system's identifiers
    are. A name written plainly is fixed, the same in both."""
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance(
        "r", xp_root / "suites" / "demo" / "one.json", XP_ID, XP_SHORT
    )
    assert [(d.name, d.system) for d in inst.domains] == [
        (f"{XP_ID}_fs", "fs"),
        (f"{XP_ID}_world", "fs"),
    ]
    assert inst.system_name(f"{XP_ID}_world") == f"{XP_SHORT}_world"
    assert inst.system_name("pinned") == "pinned"
    assert inst.collections[0].domains == {"D0": f"{XP_ID}_world"}


def test_a_run_id_is_its_build_identity_and_second_and_the_short_one_fits_12():
    from tabsdata_dev.tool.xp import ids

    t = 1790847012  # 2026-10-01T09:30:12Z
    assert ids.make("tucu", "0", t) == (XP_ID, XP_SHORT)
    assert ids.make("Al", "build_1234", t) == (
        "xp_Al_build_1234_20261001T093012",
        "alx34_0e2aec",
    )
    # 2094 is where six base-36 digits run out; the width holds until then
    assert len(ids.make("u", "7", t + 60 * 365 * 86400)[1]) == 12
    with pytest.raises(ValueError, match="before 2026-01-01"):
        ids.make("u", "0", t - 400 * 86400)


def test_two_runs_one_process_starts_are_a_second_apart(xp_root):
    from tabsdata_dev.tool.xp import ids

    first, second = ids.new(), ids.new()
    assert first == (XP_ID, XP_SHORT)
    assert second[0] == "xp_tucu_0_20261001T093013" and second[1] != first[1]


@pytest.mark.parametrize(
    "value, why",
    [
        ("${xp:name()}", "a name is a letter or digit"),
        ("${xp:name(a b)}", "a name is a letter or digit"),
        ("${xp:name(pg}", "does not close"),
    ],
)
def test_a_malformed_xp_name_is_refused(value, why):
    from tabsdata_dev.tool.xp import ids

    with pytest.raises(ValueError, match=why):
        ids.resolve({"name": value}, XP_ID, XP_SHORT)
    assert ids.resolve(["${xp:id}/${xp:short_id}", "${xp:dir}"], "a", "b") == [
        "a/b",
        "${xp:dir}",
    ]


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
        f"tdd domain create --domain {XP_ID}_fs --sys fs --name-in-system {XP_SHORT}_fs"
    )
    assert lines[1].startswith(f"tdd domain create --domain {XP_ID}_world --sys fs ")
    assert lines[2:4] == [
        f"tdd domain create-model --domain {XP_ID}_world --model world",
        f"tdd domain create-data --domain {XP_ID}_world --size 10",
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
            "--suite-run",
            "i2",
            "--format",
            "json",
        ]
    )
    assert rc == 0
    rc = _run(["run-triggers", "--project", "nope", "--dry-run", "--format", "json"])
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
                "--suite-run",
                "lbl",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _run(["create-domains", "--suite-run", "lbl", "--dry-run"]) == 0
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
    outright above it. A plan is named by its project, which carries the run's
    XP_ID: a suite dir's lane named its suite run beside it as well, saying the
    run twice and going over."""
    from tabsdata_dev.tool.xp.project import PLAN_NAME_MAX, plan_name

    ts = "20261001_124926"
    project = f"{XP_ID}_medallion_xsuite"
    name = plan_name(ts, project, "pub_period_snapshot")
    assert name == f"{ts}_{project}_pub_period_snapshot" and len(name) <= PLAN_NAME_MAX

    # and a name that overflows anyway keeps the ends and stays unique
    long_project = f"{project}_" + "x" * 200
    a = plan_name(ts, long_project, "fn_one")
    b = plan_name(ts, long_project + "y", "fn_one")
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

    def fake(argv, check, stdin_text=None, env=None, timeout=None):
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
    rc = _run(
        ["monitor-project", "--project", "p1", "--time-out", "1h", "--format", "json"]
    )
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

    def fake(argv, check, stdin_text=None, env=None, timeout=None):
        args = argv[argv.index("tdk") + 1 :]
        if args[:2] == ["trx", "list"] and "--monitor" in args:
            seconds, rc = queue.pop(0)
            if timeout is not None and seconds > timeout:
                now[0] += timeout
                raise subprocess.TimeoutExpired(argv, timeout)
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


def _monitor_events(capsys, time_out="1h"):
    rc = _run(
        [
            "monitor-project",
            "--project",
            "p1",
            "--time-out",
            time_out,
            "--format",
            "json",
        ]
    )
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


def test_the_monitor_fails_the_run_once_its_time_out_passes(
    xp_root, monkeypatch, capsys
):
    """A watch is never without an end: transactions still running at the
    time_out fail the run, through outages and retries alike."""
    watched = _fake_monitor(monkeypatch, [(40, 1), (600, 0)])
    rc, events = _monitor_events(capsys, time_out="2m")
    err = [e for e in events if e["event"] == "error"][0]
    assert rc == 1 and watched == [1]
    assert (
        "still has transactions running after the monitor's time_out (2m)"
        in err["message"]
    )


#: tdk's words when the port-forward is down, as the eks smoke of 2026-10-04 saw
#: them -- boxed, and wrapped where the box chose.
REFUSED = (
    "│ Failed to create collection: HTTPConnectionPool(host='127.0.0.1', port=11000): │\n"
    "│ Max retries exceeded (Caused by NewConnectionError(\"HTTPConnection(host='127.0.0.1', │\n"
    "│ port=11000): Failed to establish a new │\n"
    '│ connection: [Errno 61] Connection refused")) │'
)


def _fake_tdk(monkeypatch, replies):
    """Stand in for tdk and the clock: each call takes the next (exit code,
    stderr) from ``replies``; every call costs a second."""
    import subprocess
    import types

    from tabsdata_dev.tool.xp import shell

    now = [0.0]
    queue = list(replies)
    sent = []

    def fake(argv, check, stdin_text=None, env=None, timeout=None):
        sent.append(stdin_text)
        now[0] += 1
        rc, err = queue.pop(0)
        return subprocess.CompletedProcess(argv, rc, "{}" if rc == 0 else "", err)

    def sleep(seconds):
        now[0] += seconds

    monkeypatch.setattr(shell, "run_cmd", fake)
    monkeypatch.setattr(
        shell, "time", types.SimpleNamespace(monotonic=lambda: now[0], sleep=sleep)
    )
    return sent


def test_a_tdk_call_that_could_not_connect_is_sent_again(xp_root, monkeypatch):
    """A port-forward drop failed three collection creates in the seconds before
    its relaunch, and the suite with them. The request never left, so it is safe
    to send again -- stdin and all."""
    from tabsdata_dev.tool.xp import shell

    sent = _fake_tdk(monkeypatch, [(1, REFUSED), (1, REFUSED), (0, "")])
    r = shell.tdk(
        ["collection", "create", "--conn-file", "-"], want_json=False, stdin_text="c"
    )
    assert r.returncode == 0 and sent == ["c", "c", "c"]
    sent = _fake_tdk(monkeypatch, [(1, REFUSED), (0, "")])
    assert shell.tdk_read(["collection", "list"]) == ({}, "")
    assert len(sent) == 2


def test_a_tdk_call_that_cannot_connect_fails_once_the_grace_is_spent(
    xp_root, monkeypatch
):
    from tabsdata_dev.tool.xp import shell, state

    sent = _fake_tdk(monkeypatch, [(1, REFUSED)] * 100)
    with pytest.raises(state.XpError, match="Connection refused"):
        shell.tdk(["collection", "create"], want_json=False)
    per_try = shell.NOT_CONNECTED_PAUSE + 1
    assert len(sent) == int(shell.NOT_CONNECTED_GRACE // per_try) + 1


def test_a_tdk_call_that_reached_the_server_is_never_sent_again(xp_root, monkeypatch):
    """A reset mid-request may have landed a create, and any other failure is
    tdk's answer: either fails at once."""
    from tabsdata_dev.tool.xp import shell, state

    for err in ("│ ('Connection aborted.', ConnectionResetError(54)) │", "│ exists │"):
        sent = _fake_tdk(monkeypatch, [(1, err)])
        with pytest.raises(state.XpError):
            shell.tdk(["collection", "create"], want_json=False)
        assert len(sent) == 1


def test_a_monitor_is_never_without_a_time_out(xp_root, capsys):
    assert _run(["monitor-project", "--project", "p1"]) == 1  # argparse: required
    assert "required: --time-out" in capsys.readouterr().err
    rc = _run(["run-triggers", "--project", "p1", "--monitor"])
    assert rc == 1 and "--time-out <VALUE><UNIT>" in capsys.readouterr().err


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


@pytest.mark.parametrize("planned", [True, False])
def test_lanes_share_their_columns_from_the_first_line(
    xp_root, monkeypatch, capsys, planned
):
    """Lanes one after another, their labels and totals unlike: every line
    keeps the same columns, and with plans [N/M] is the run's from the first."""
    import sys

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import lanes, pointers, state
    from tabsdata_dev.tool.xp.reporter import strip_ansi

    monkeypatch.setenv("TDD_PARALLELISM", "1")
    labels = {"a": "perf/a", "b": "perf/a_much_longer_label"}
    monkeypatch.setattr(pointers, "suite_of_instance", lambda i: labels[i])

    def child(lane, total, note):
        steps = [
            {
                "command": "xp", "event": "info", "message": "-", "xp": "step",
                "suite": labels[lane], "n": n, "total": total,
                "action": "create-domain", "path": "d", "seconds": 0.1,
                "ok": True, "note": note if n == 1 else "", "step_error": "",
            }
            for n in range(1, total + 1)
        ]  # fmt: skip
        done = {"command": "xp", "event": "ok", "message": "-", "xp": "summary"}
        code = "import json\n" + "".join(
            f"print(json.dumps({s!r}))\n" for s in [*steps, done]
        )
        return (lane, [sys.executable, "-c", code, "--suite-run", lane])

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    plans = {"a": lanes.LanePlan(12, ("postgres_cdc",)), "b": lanes.LanePlan(3)}
    failed = lanes.dispatch(
        "t",
        [child("a", 12, "postgres_cdc"), child("b", 3, "")],
        fatal=False,
        plans=plans if planned else None,
    )
    assert failed == []
    lines = [
        ln
        for ln in map(strip_ansi, capsys.readouterr().err.splitlines())
        if "perf/" in ln
    ]
    assert len(lines) == 15
    assert len({ln.index(" - create-domain") for ln in lines}) == 1
    if planned:
        # A known note widens the column: the path holds on every line too.
        paths = {ln.index(" - d", ln.index("create-domain")) for ln in lines}
        assert len(paths) == 1
        assert lines[0].startswith("[ 1/15] perf/a ")
        assert lines[-1].startswith("[15/15] perf/a_much_longer_label -  [ 3/3]")
    else:
        assert lines[-1].startswith("[15/15] ")


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


def _tdd(name, domain, command, *options, **extra):
    """A tdd step running a `tdd domain` verb on one of the suite's domains."""
    return {
        "tdd": {
            "name": name,
            "tool": "domain",
            "command": command,
            "options": ["--domain", N(domain), *options],
            **extra,
        }
    }


def _sleep(name, time="1s", **extra):
    return {"sleep": {"name": name, "time": time, **extra}}


def _wait(name, *names):
    return {"wait": {"name": name, "for": list(names)}}


def _bg(name, *entries, **extra):
    return {"background": {"name": name, "actions": list(entries), **extra}}


def _loop(name, repeat, *entries, **extra):
    return {"loop": {"name": name, "repeat": repeat, "actions": list(entries), **extra}}


def _par(name, *entries, lanes=0):
    return {"parallel": {"name": name, "lanes": lanes, "actions": list(entries)}}


def _tmo(name, time, *entries, stop=True):
    return {
        "timeout": {
            "name": name,
            "time": time,
            "stop_on_timeout": stop,
            "actions": list(entries),
        }
    }


ACTIONS = [
    _loop(
        "cycle",
        3,
        _tdd("load", "world", "create-data"),
        _loop(
            "churn",
            10,
            _sleep("pause"),
            _tdd("city", "world", "modify-data", "--entity", "city", "--ops", "Insert"),
            _tdd("files", "fs", "modify-data"),
        ),
        _tdd("empty", "world", "delete-data"),
        _tdd("drop", "world", "delete-model"),
        _tdd("model", "world", "create-model", "--force", "--model", "world"),
    )
]


def _actions_suite(xp_root, script=ACTIONS):
    path = xp_root / "suites" / "act" / "one.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_stages(SUITE) + [{"actions": script}, MONITOR]))
    return path


def _actions_instance(xp_root, script):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    return build_instance("i", _actions_suite(xp_root, script), XP_ID, XP_SHORT)


def _instance(xp_root, name="i"):
    args = ["create-instance", "--suite", "act/one", *_suites_dir(xp_root)]
    assert _run([*args, "--suite-run", name]) == 0


def _fake_steps(monkeypatch, body=None):
    """Stand in for every step that runs something: `body(label)`, in order."""
    from tabsdata_dev.tool.xp import actions

    ran: list[str] = []

    def step(a, run, label):
        if body is not None:
            body(label, run)
        ran.append(label)

    monkeypatch.setattr(actions, "_step", step)
    return ran


def test_an_actions_script_counts_its_steps_through_every_loop(xp_root):
    from tabsdata_dev.tool.xp import actions
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", _actions_suite(xp_root))
    # 3 x (load + 10 x (city + files) + empty + drop + model); sleeps run nothing
    assert actions.count(inst.actions, actions.Selection()) == 3 * (1 + 10 * 2 + 3)


@pytest.mark.parametrize(
    "script, why",
    [
        ([{"tdd": {"tool": "domain", "command": "x"}}], "name"),
        ([_sleep("1st")], "a letter"),
        ([{}], "exactly one of"),
        ([{**_sleep("x"), **_wait("y", "x")}], "has sleep, wait"),
        (
            [{"tdd": {"name": "x", "tool": "venv", "command": "create"}}],
            "'venv' is a shell function",
        ),
        (
            [{"tdd": {"name": "x", "tool": "domain", "command": "m", "opts": []}}],
            "Extra inputs",
        ),
        (
            [
                {
                    "tdd": {
                        "name": "x",
                        "tool": "d",
                        "command": "m",
                        "options": ["${xp:nope}"],
                    }
                }
            ],
            r"\$\{xp:nope\} is not a token",
        ),
        ([_loop("x", 0, _sleep("s"))], "repeat must be >= 1"),
        ([_bg("x")], "holds no actions"),
        ([_sleep("x", "5")], "is not <VALUE><UNIT>"),
        ([_tmo("t", "soon", _sleep("s"))], "is not <VALUE><UNIT>"),
        ([_sleep("x", tags=["9"])], "tag '9'"),
        ([_sleep("x"), _sleep("x")], "'x' is used twice"),
        ([_wait("w", "later"), _sleep("later")], "not an action before it"),
        (
            # out of reach: inside another entry's block
            [_bg("g", _tdd("inner", "world", "delete-data")), _wait("w", "inner")],
            "'inner', which is not an action before it",
        ),
        (
            # the block that holds the wait: it would wait for itself
            [_loop("g", 1, _wait("w", "g"))],
            "'g', which is not an action before it",
        ),
        ([_sleep("s"), _wait("w", "s")], "a sleep: there is nothing"),
        (
            [_bg("b", _sleep("z")), _par("p", _wait("w", "b"), lanes=2)],
            "inside parallel 'p', which bounds its lanes",
        ),
        ([{"python": {"name": "c", "script": "scripts/nope.py"}}], "no script"),
        ([{"python": {"name": "c", "script": "../x.py"}}], "inside the suite dir"),
        ([{"exe": {"name": "e", "program": " "}}], "names no program"),
    ],
)
def test_an_actions_script_is_refused_when_the_suite_is_read(xp_root, script, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _actions_suite(xp_root, script))


def test_a_wait_reaches_back_here_in_enclosing_lists_and_in_earlier_stages(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    script = [
        _bg("bg", _tdd("c1", "world", "modify-data")),
        _loop(
            "g",
            2,
            _bg("one", _tdd("c2", "fs", "modify-data")),
            _wait("w", "one", "bg"),  # a sibling and an outer entry
        ),
        _wait("w2", "g"),
        _par("p", _wait("w3", "bg")),  # an unbounded parallel may wait
    ]
    assert build_instance("i", _actions_suite(xp_root, script)).actions[
        2
    ].wait.for_ == ["g"]
    # one script across stages: a later stage's wait finds an earlier stage's block
    doc = [
        {"domains": calls("world", "fs")},
        {"actions": [_bg("churn", _tdd("c", "world", "modify-data"))]},
        MONITOR,
        {"actions": [_wait("settle", "churn")]},
    ]
    assert [
        a.name for a in build_instance("i", _staged_suite(xp_root, doc)).actions
    ] == [
        "churn",
        "settle",
    ]


def test_dry_run_run_actions_prints_the_script_in_order(xp_root, capsys):
    _actions_suite(xp_root)
    _instance(xp_root)
    capsys.readouterr()
    rc = _run(["run-actions", "--suite-run", "i", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = [ln for ln in out.splitlines() if ln.startswith(("tdd ", "sleep "))]
    first = lines[: lines.index(f"tdd domain delete-model --domain {XP_ID}_world") + 2]
    # a step runs as written: nothing is filled in
    assert first[0] == f"tdd domain create-data --domain {XP_ID}_world"
    assert first[1:4] == [
        "sleep 1",
        f"tdd domain modify-data --domain {XP_ID}_world --entity city --ops Insert",
        f"tdd domain modify-data --domain {XP_ID}_fs",
    ]
    assert first[4] == "sleep 1"  # the inner loop's next pass
    assert first[-3:] == [
        f"tdd domain delete-data --domain {XP_ID}_world",
        f"tdd domain delete-model --domain {XP_ID}_world",
        f"tdd domain create-model --domain {XP_ID}_world --force --model world",
    ]
    assert len([ln for ln in lines if ln.startswith("tdd ")]) == 3 * 24
    # each step is a step of the run, labelled with the blocks and passes it is under
    assert "cycle 1/3 > churn 10/10 > city" in err


def test_dry_run_marks_what_goes_to_the_background_and_what_waits(xp_root, capsys):
    _actions_suite(
        xp_root,
        [
            _tdd("seed", "world", "create-data"),
            _bg("churn", _loop("pass", 2, _tdd("change", "world", "modify-data"))),
            _wait("settle", "churn"),
            _tmo("bounded", "5m", _tdd("reset", "world", "delete-data")),
        ],
    )
    _instance(xp_root)
    capsys.readouterr()
    rc = _run(["run-actions", "--suite-run", "i", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert out.splitlines()[:8] == [
        f"tdd domain create-data --domain {XP_ID}_world",
        "# churn: starts in the background",
        f"tdd domain modify-data --domain {XP_ID}_world",
        f"tdd domain modify-data --domain {XP_ID}_world",
        "# churn: ends",
        "# settle: wait for churn",
        "# bounded: at most 5m",
        f"tdd domain delete-data --domain {XP_ID}_world",
    ]


def test_a_background_block_runs_side_by_side_until_waited_for(xp_root, monkeypatch):
    """`churn` starts and the script goes on: `seed`, after it, runs while
    churn is still inside its step -- churn only finishes once seed has run, so
    a churn that held the script would never finish. `reset` waits for it."""
    import threading

    from tabsdata_dev.tool.xp import actions

    seeded = threading.Event()

    def body(label, run):
        if label == "churn > change":
            assert seeded.wait(5), "churn held the script"
        if label == "seed":
            seeded.set()

    ran = _fake_steps(monkeypatch, body)
    inst = _actions_instance(
        xp_root,
        [
            _bg("churn", _tdd("change", "world", "modify-data")),
            _tdd("seed", "world", "create-data"),
            _wait("settle", "churn"),
            _tdd("reset", "world", "delete-data"),
        ],
    )
    actions.run_script(inst, "p", actions.Selection())
    assert ran == ["seed", "churn > change", "reset"]


def test_a_loop_pass_ends_when_everything_it_started_has(xp_root, monkeypatch):
    """A background block inside a pass is waited for at the end of the pass:
    pass 2 does not start while pass 1's background step still runs."""
    import threading
    import time

    from tabsdata_dev.tool.xp import actions

    lock = threading.Lock()
    events: list[str] = []

    def body(label, run):
        with lock:
            events.append(f"start {label}")
        if label.endswith("slow"):
            time.sleep(0.1)
        with lock:
            events.append(f"end {label}")

    _fake_steps(monkeypatch, body)
    inst = _actions_instance(
        xp_root,
        [
            _loop(
                "g",
                2,
                _bg("bg", _tdd("slow", "world", "modify-data")),
                _tdd("quick", "fs", "modify-data"),
            )
        ],
    )
    actions.run_script(inst, "p", actions.Selection())
    assert events.index("end g 1/2 > bg > slow") < events.index(
        "start g 2/2 > bg > slow"
    )


def test_a_failed_background_step_stops_the_script_and_is_its_error(
    xp_root, monkeypatch
):
    """The first failure anywhere is the run's: what still runs stops at its
    next step or pause, and nothing after it starts."""
    from tabsdata_dev.tool.xp import actions, state

    def body(label, run):
        if label == "bad > boom":
            state.die("bad step failed")

    ran = _fake_steps(monkeypatch, body)
    inst = _actions_instance(
        xp_root,
        [
            _bg(
                "slow",
                _loop(
                    "ticks",
                    50,
                    _sleep("nap", "0.05s"),
                    _tdd("tick", "world", "modify-data"),
                ),
            ),
            _bg("bad", _tdd("boom", "fs", "modify-data")),
            _wait("settle", "bad"),
            _tdd("after", "world", "delete-data"),
        ],
    )
    with pytest.raises(state.XpError, match="bad step failed"):
        actions.run_script(inst, "p", actions.Selection())
    assert "after" not in ran
    assert len([c for c in ran if c.startswith("slow")]) < 50


def test_tags_pick_steps_blocks_pass_theirs_on_and_a_skipped_wait_is_met(
    xp_root, monkeypatch
):
    from tabsdata_dev.tool.xp import actions

    script = [
        _bg(
            "churn",
            _tdd("change", "world", "modify-data"),
            _tdd("slow", "world", "modify-data", tags=["slow"]),
            tags=["churn"],
        ),
        _wait("settle", "churn"),
        _tdd("verify", "fs", "modify-data", tags=["check"]),
        _tdd("plain", "fs", "modify-data"),
    ]

    def ran(**sel):
        steps = _fake_steps(monkeypatch)
        inst = _actions_instance(xp_root, script)
        actions.run_script(inst, "p", actions.Selection(**sel))
        return sorted(steps)

    every = ["churn > change", "churn > slow", "plain", "verify"]
    assert ran() == every
    assert ran(tags=frozenset({"churn"})) == ["churn > change", "churn > slow"]
    assert ran(tags=frozenset({"churn", "check"})) == [
        "churn > change",
        "churn > slow",
        "verify",
    ]
    assert ran(skip=frozenset({"slow"})) == ["churn > change", "plain", "verify"]
    assert ran(tags=frozenset({"churn"}), skip=frozenset({"slow"})) == [
        "churn > change"
    ]
    # nothing of churn runs: its wait is met at once, and the rest goes on
    assert ran(skip=frozenset({"churn"})) == ["plain", "verify"]
    assert ran(none=True) == []
    sel = actions.Selection(tags=frozenset({"b", "a"}), skip=frozenset({"c"}))
    assert sel.flags() == ["--tags", "a,b", "--skip-tags", "c"]
    assert actions.count(_actions_instance(xp_root, script).actions, sel) == 0


def test_a_parallel_runs_side_by_side_its_lanes_at_a_time_and_joins(
    xp_root, monkeypatch
):
    import threading
    import time

    from tabsdata_dev.tool.xp import actions

    def peak(lanes):
        lock = threading.Lock()
        now, top = [0], [0]

        def body(label, run):
            if label.startswith("p > "):
                with lock:
                    now[0] += 1
                    top[0] = max(top[0], now[0])
                time.sleep(0.05)
                with lock:
                    now[0] -= 1

        ran = _fake_steps(monkeypatch, body)
        inst = _actions_instance(
            xp_root,
            [
                _par(
                    "p",
                    *(_tdd(f"s{i}", "world", "modify-data") for i in range(4)),
                    lanes=lanes,
                ),
                _tdd("after", "fs", "modify-data"),
            ],
        )
        actions.run_script(inst, "p", actions.Selection())
        assert ran[-1] == "after"  # joined before the script went on
        return top[0]

    assert peak(0) == 4
    assert peak(1) == 1


def test_a_timeout_fails_the_run_or_leaves_its_actions_running(xp_root, monkeypatch):
    import threading

    from tabsdata_dev.tool.xp import actions, state

    release = threading.Event()

    def body(label, run):
        if label.endswith("hang"):
            # until the run lets it go, or it is the run's end
            while not (release.is_set() or run.stop.is_set()):
                release.wait(0.01)

    ran = _fake_steps(monkeypatch, body)
    hang = _tdd("hang", "world", "modify-data")
    inst = _actions_instance(
        xp_root, [_tmo("t", "0.1s", hang), _tdd("next", "fs", "modify-data")]
    )
    with pytest.raises(state.XpError, match="timeout 't': its actions ran past 0.1s"):
        actions.run_script(inst, "p", actions.Selection())
    assert "next" not in ran

    ran = _fake_steps(monkeypatch, body)
    inst = _actions_instance(
        xp_root,
        [_tmo("t", "0.1s", hang, stop=False), _tdd("next", "fs", "modify-data")],
    )
    # the run's end stops it, and lets it end before the run closes
    actions.run_script(inst, "p", actions.Selection())
    assert ran == ["next", "t > hang"]


def test_one_shot_runs_the_actions_after_the_triggers_unless_told_not_to(
    xp_root, capsys
):
    _actions_suite(xp_root, [_tdd("b", "world", "modify-data", tags=["churn"])])

    def lines(*extra):
        rc = _run(
            [
                "one-shot",
                "--suite",
                "act/one",
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

    # each one-shot is a suite run of its own: its domain is named by its XP_ID
    def steps(ran):
        return [
            ln for ln in ran if ln.startswith("tdd domain modify-data --domain xp_")
        ]

    ran = lines()
    at = ran.index(steps(ran)[0])
    monitors = [i for i, ln in enumerate(ran) if ln.startswith("tdd tdk trx list")]
    # watched once for the triggers, then again for what the changes started
    assert monitors[0] < at < monitors[1]
    assert not steps(lines("--no-actions"))
    assert not steps(lines("--skip-tags", "churn"))
    assert steps(lines("--tags", "churn"))
    assert (
        _run(
            [
                "one-shot",
                "--suite",
                "act/one",
                *_suites_dir(xp_root),
                "--dry-run",
                "--no-actions",
                "--tags",
                "x",
            ]
        )
        == 1
    )
    assert "takes no --tags" in capsys.readouterr().err


def test_a_retired_live_or_execute_stage_is_refused_naming_actions(xp_root):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    for kind in ("live", "execute"):
        with pytest.raises(
            state.XpError,
            match=f"'{kind}' is no longer read -- it is an 'actions' stage",
        ):
            build_instance("i", _staged_suite(xp_root, [{kind: []}]))


STAGED = [
    {"_comment": "a comment entry reads as nothing"},
    {"domains": calls("world", "fs", "world", 10)},
    {"actions": [_tdd("early", "world", "modify-data", "--ops", "Insert")]},
    {
        "collections": [
            {
                "name": "src",
                "type": "local_file_in",
                "connection_template": "connection-file:connections/local_file_in.yaml",
                "group": "sources",
                "domains": {"D0": N("world")},
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
    MONITOR,
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
        "actions",
        "collections",
        "functions",
        "domains",
        "triggers",
        "monitor",
    ]
    # every entry of a kind, across its stages, for the phase verbs
    assert [d.name for d in inst.domains] == [f"{PH}_world", f"{PH}_fs"]
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
        match='a single object, a form xp no longer reads.*"monitor": \\{"time_out"',
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
        ([{"monitor": 5}], "monitor takes"),
        ([{"monitor": True}], "monitor takes"),
        ([{"monitor": {}}], "how long it may watch"),
        ([{"monitor": {"time_out": "30"}}], "time_out: '30' is not"),
        ([{"domains": {}}], "domains takes a list"),
        (
            [
                {
                    "collections": [
                        {
                            "name": "c",
                            "type": "t",
                            "group": "g",
                            "domains": {"D0": N("d")},
                        }
                    ]
                },
                {"domains": calls("d", "fs")},
            ],
            f"collection 'c' names domain '{PH}_d', created by a later stage",
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
            "--suite-run",
            "i",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    rc = _run(["run-suite", "--suite-run", "i", "--project", "p", "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    lines = [ln for ln in out.splitlines() if ln.startswith("tdd ")]

    def at(prefix):
        return next(i for i, ln in enumerate(lines) if ln.startswith(prefix))

    order = [
        at(f"tdd domain create --domain {XP_ID}_world --sys fs"),  # stage 1: world
        at(
            f"tdd domain modify-data --domain {XP_ID}_world --ops Insert"
        ),  # live, before the project
        at("tdd tdk project create --name p"),  # the first project stage creates it
        at("tdd tdk collection create --proj p --name src"),
        at("tdd tdk fn register --update --proj p --coll src"),
        at("tdd tdk fn trigger --proj p --coll src --name pub"),
        at("tdd tdk trx list --proj p --monitor"),
    ]
    assert order == sorted(order)
    # the second domains stage runs where it stands, between them
    assert order[4] < at(f"tdd domain create --domain {XP_ID}_fs --sys fs") < order[5]
    # "enabled": false registers it disabled
    assert lines[order[4]].endswith(" --disabled")


def test_every_step_of_a_suite_counts_out_of_the_whole_suite(xp_root, capsys):
    """The [N/M] total is the suite's from the first step: the phases plan
    their own steps only as they start, and an actions stage plans none."""
    import re

    _staged_suite(xp_root)
    assert (
        _run(
            [
                "create-instance",
                "--suite",
                "staged/one",
                *_suites_dir(xp_root),
                "--suite-run",
                "i",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert _run(["run-suite", "--suite-run", "i", "--project", "p", "--dry-run"]) == 0
    _, err = capsys.readouterr()
    counts = [
        (int(n), int(m))
        for n, m in re.findall(r"^staged/one - \[\s*(\d+)/(\d+)\] - ", err, re.M)
    ]
    assert [n for n, _ in counts] == list(range(1, len(counts) + 1))
    assert {m for _, m in counts} == {len(counts)}


def test_the_note_column_is_as_wide_as_the_longest_note_a_suite_knows(xp_root, capsys):
    """The actions' labels and the triggers' plans are known before they
    run, so the note column fits the longest of them from the first line."""
    from tabsdata_dev.tool.xp.reporter import strip_ansi

    _actions_suite(xp_root)
    _instance(xp_root)
    capsys.readouterr()
    assert _run(["run-suite", "--suite-run", "i", "--project", "p", "--dry-run"]) == 0
    _, err = capsys.readouterr()
    notes = [
        line.split(" - ")[5]
        for line in map(strip_ansi, err.splitlines())
        if line.startswith("act/one - [")
    ]
    assert "cycle 3/3 > churn 10/10 > files" in [n.strip() for n in notes]
    assert any(n.startswith("plan=") for n in notes)
    assert {len(n) for n in notes} == {max(len(n.strip()) for n in notes)}


def test_a_step_line_keeps_its_columns_whatever_its_path():
    from tabsdata_dev.tool.xp.reporter import render_step

    def line(path, seconds):
        event = {"suite": "s", "n": 3, "total": 12, "action": "modify-data"}
        return render_step({**event, "path": path, "seconds": seconds})

    short, long = line("d", 0.33), line("xp_" + "x" * 120, 180.53)
    assert short.index(" - d") == long.index(" - xp_")
    assert short.startswith("s - [ 3/12] - modify-data ")


def test_a_step_line_is_painted_by_its_outcome_on_a_terminal(monkeypatch):
    import io

    from tabsdata_dev.tool.xp.reporter import render_step, strip_ansi

    class Terminal(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    event = {"suite": "s", "n": 1, "total": 2, "action": "sentinel", "path": "p"}
    passed = render_step({**event, "seconds": 180.5}, Terminal())
    failed = render_step({**event, "seconds": 0.5, "ok": False}, Terminal())

    assert passed.startswith("\033[38;5;179ms\033[0m - \033[38;5;139m[1/2]")
    assert "\033[38;5;73msentinel" in passed and "\033[38;5;73msentinel" in failed
    assert "\033[38;5;173m 180.50s" in passed and "\033[38;5;67m   0.50s" in failed
    assert "\033[38;5;71mPASSED " in passed and "\033[38;5;167mFAILED " in failed
    assert (
        failed.endswith("\033[38;5;137mp\033[0m") and "\033[37m" not in passed + failed
    )
    assert strip_ansi(passed) == render_step({**event, "seconds": 180.5})
    assert render_step({**event, "seconds": 0.5}, io.StringIO()) == render_step(
        {**event, "seconds": 0.5}
    )


def test_an_actions_stages_background_blocks_run_through_later_stages(
    xp_root, monkeypatch
):
    """An actions stage returns with its background blocks still running; a
    later actions stage waits for them by name; the suite's end waits for the
    rest."""
    import threading

    from tabsdata_dev.tool.xp import actions
    from tabsdata_dev.tool.xp.models import build_instance

    released = threading.Event()

    def body(label, run):
        if label == "bg > change":
            assert released.wait(5)

    done = _fake_steps(monkeypatch, body)
    doc = [
        {"domains": calls("world", "fs")},
        {"actions": [_bg("bg", _tdd("change", "world", "modify-data"))]},
        {"actions": [_wait("settle", "bg"), _tdd("after", "world", "delete-data")]},
    ]
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    inst = build_instance("i", _staged_suite(xp_root, doc))
    session = actions.Session(inst, "p")
    session.stage(inst.stages[1].actions)  # returns while bg still runs
    assert done == []
    released.set()  # a stage in between, running beside it
    session.stage(inst.stages[2].actions)
    session.finish()
    assert done == ["bg > change", "after"]


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
        {"actions": [_sleep("settle", "2m")]},
        {"sentinel": [entry]},
    ]


def test_a_sentinel_stage_reads_and_sleep_takes_a_unit(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    inst = build_instance("i", _staged_suite(xp_root, _sentinel_suite()))
    assert [s.kind for s in inst.stages] == ["collections", "actions", "sentinel"]
    assert inst.actions[0].sleep.seconds == 120.0
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
            [{"actions": [_sleep("x", "soon")]}],
            "time: 'soon' is not <VALUE><UNIT>",
        ),
        (
            [{"actions": [_sleep("x", 30)]}],
            "time: 30 is not <VALUE><UNIT>",
        ),
        (
            [{"actions": [{"sleep": {"name": "x", "secs": 30}}]}],
            "secs\n  Extra inputs are not permitted",
        ),
    ],
)
def test_a_bad_sentinel_or_duration_is_refused_when_read(xp_root, doc, why):
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    with pytest.raises(state.XpError, match=why):
        build_instance("i", _staged_suite(xp_root, doc))


def _fake_sentinel_tdk(
    monkeypatch,
    looks,
    *,
    column="sentinel_key",
    found_in=(),
    unreadable=None,
    empty=(),
):
    """shell.tdk answering `table versions` from `looks`, and shell.tdk_read
    answering `table schema` with `column` -- no columns at all for the
    versions `empty` -- and `table data` with the key in the versions
    `found_in`. `unreadable` maps a version to the error of its next read (one
    read each, unless the value is sticky: a list). Returns the log of (verb,
    version, sql)."""
    from tabsdata_dev.tool.xp import project, shell

    monkeypatch.setattr(project.time, "sleep", lambda s: None)
    looks = iter(looks)
    last: list = []
    calls: list = []
    unreadable = dict(unreadable or {})

    def tdk(args, want_json=True, check=True, stdin_text=None):
        assert args[:2] == ["table", "versions"] and "--max-result" in args
        nonlocal last
        last = next(looks, last)
        return last

    def tdk_read(args):
        verb, vid = args[1], args[args.index("--version") + 1]
        sql = args[args.index("--sql") + 1] if "--sql" in args else None
        calls.append((verb, vid, sql))
        why = unreadable.get(vid)
        if why is not None:
            if not isinstance(why, list):
                del unreadable[vid]
            return None, why if isinstance(why, str) else why[0]
        if verb == "schema" and vid in empty:
            return [], ""
        if verb == "schema":
            return [
                {"name": column, "type": "String"},
                {"name": "ts", "type": "Datetime"},
            ], ""
        return ([{column: "k"}] if vid in found_in else []), ""

    monkeypatch.setattr(shell, "tdk", tdk)
    monkeypatch.setattr(shell, "tdk_read", tdk_read)
    return calls


def test_a_sentinel_reads_every_version_once_until_one_holds_the_key(
    xp_root, monkeypatch
):
    """Each flush of a stream is a version of its own, so every version is
    read -- once, since a committed one never changes; one that cannot be read
    yet is tried again. The latch opens on the version holding the key."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    calls = _fake_sentinel_tdk(
        monkeypatch,
        [[{"id": "v1"}, {"id": "v2"}], [{"id": "v1"}, {"id": "v2"}, {"id": "v3"}]],
        found_in={"v3"},
        unreadable={"v2": "not yet"},
    )
    s = Sentinel(
        collection="c", table="xp_sentinel_changes", wait_for_key="it's", time_out="1m"
    )
    project.wait_sentinels("p", [s])
    data = [(vid, sql) for verb, vid, sql in calls if verb == "data"]
    assert [vid for vid, _ in data] == ["v1", "v2", "v2", "v3"]
    assert data[0][1] == (
        'SELECT "sentinel_key" FROM xp_sentinel_changes '
        "WHERE \"sentinel_key\" = 'it''s'"
    )
    assert [c[:2] for c in calls if c[0] == "schema"] == [("schema", "v1")]  # once


def test_a_sentinel_reads_the_key_column_as_the_database_spells_it(
    xp_root, monkeypatch
):
    """DB2 upper-cases unquoted names, so its stream carries SENTINEL_KEY, and
    tdk's SQL matches case: the column is taken from the schema and quoted."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    calls = _fake_sentinel_tdk(
        monkeypatch, [[{"id": "v1"}]], column="SENTINEL_KEY", found_in={"v1"}
    )
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="1m")
    project.wait_sentinels("p", [s])
    [(_, _, sql)] = [c for c in calls if c[0] == "data"]
    assert sql == 'SELECT "SENTINEL_KEY" FROM t WHERE "SENTINEL_KEY" = \'k\''


def test_a_sentinel_that_never_arrives_fails_at_its_time_out(xp_root, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    _fake_sentinel_tdk(monkeypatch, [[{"id": "v1"}]])
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="0s")
    with pytest.raises(
        state.XpError,
        match=r"sentinel 'k' not in any version of c/t after 0s \(1 version\(s\) read\)$",
    ):
        project.wait_sentinels("p", [s])


def test_a_sentinel_says_why_the_versions_it_could_not_read_failed(
    xp_root, monkeypatch
):
    """Versions that exist but cannot be read are not "0 read": the time-out
    counts them and gives the last error, rather than leaving it in run.log."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    _fake_sentinel_tdk(
        monkeypatch,
        [[{"id": "v1"}, {"id": "v2"}]],
        unreadable={"v1": ["SQL Error: boom"], "v2": ["SQL Error: boom"]},
    )
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="0s")
    with pytest.raises(
        state.XpError,
        match=r"\(0 version\(s\) read; 2 could not be read: SQL Error: boom\)",
    ):
        project.wait_sentinels("p", [s])


def test_a_version_with_no_columns_is_passed_over_not_fatal(xp_root, monkeypatch):
    """A stream from its tail flushes before the first sentinel row, and an
    empty flush is a version with no columns at all: it holds no key, and says
    nothing of the table's columns -- the key is looked for in the next."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    calls = _fake_sentinel_tdk(
        monkeypatch, [[{"id": "v1"}, {"id": "v2"}]], empty={"v1"}, found_in={"v2"}
    )
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="1m")
    project.wait_sentinels("p", [s])
    assert [c[:2] for c in calls] == [
        ("schema", "v1"),
        ("schema", "v2"),
        ("data", "v2"),
    ]


def test_a_table_without_the_key_column_fails_at_once(xp_root, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, state
    from tabsdata_dev.tool.xp.models import Sentinel

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    _fake_sentinel_tdk(monkeypatch, [[{"id": "v1"}]], column="other")
    s = Sentinel(collection="c", table="t", wait_for_key="k", time_out="1h")
    with pytest.raises(state.XpError, match="has no sentinel_key column in any case"):
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
            "--suite-run",
            "i",
        ]
    )
    assert rc == 0
    capsys.readouterr()
    rc = _run(["run-suite", "--suite-run", "i", "--project", "p", "--dry-run"])
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
    """${xp:dir} is the run's <scratch>/work, made on first use;
    ${xp:project} needs a project; any other ${xp:...} is a typo, refused when
    the suite is read."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state, work
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    expanded = work.expand("${xp:dir}/ops.jsonl")
    assert expanded == f"{work.work_dir()}/ops.jsonl" and work.work_dir().is_dir()
    assert work.expand("p=${xp:project}", "proj") == "p=proj"
    with pytest.raises(state.XpError, match=r"\$\{xp:project\} has no value here"):
        work.expand("${xp:project}")
    doc = [{"domains": calls("d", "fs", "world", 1, "--emit-ops", "${xp:workdir}/x")}]
    with pytest.raises(state.XpError, match=r"\$\{xp:workdir\} is not a token"):
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
        {"domains": calls("d", "fs", "world", 1, "--emit-ops", "${xp:dir}/ops.jsonl")}
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    create, model, data = inst.stages[0].domains
    assert [d.name for d in inst.domains] == [f"{PH}_d"] and inst.domains[
        0
    ].system == "fs"
    argv = domains.call_argv(inst, create)
    assert argv[-6:-2] == ["--domain", f"{PH}_d", "--sys", "fs"]
    assert argv[-2:] == ["--name-in-system", "use00_000000_d"]
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
        (
            [{"domains": calls("d", "fs") + calls("d", "fs")}],
            f"'{PH}_d' is created twice",
        ),
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


def _python_suite(xp_root, entries):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import state
    from tabsdata_dev.tool.xp.models import build_instance

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    return build_instance("i", _staged_suite(xp_root, [{"actions": entries}]))


def _py(name, script, *params, **extra):
    return {"python": {"name": name, "script": script, "params": list(params), **extra}}


@pytest.fixture
def launcher(monkeypatch, xp_root):
    """`uv run` stood in for by this python, and `tdd-exe` by a fake path: the
    step runs as it would, on what the test controls."""
    import sys

    from tabsdata_dev.tool.xp import actions

    monkeypatch.setenv("TDD_DIR", str(xp_root.parent / "tdd"))
    real = actions.argv_of

    def argv_of(a, inst, project):
        argv = real(a, inst, project)
        if argv[:3] == ["uv", "run", "--no-project"]:
            rest = argv[3:]
            while rest[:1] == ["--with"]:
                rest = rest[2:]
            return [sys.executable, *rest]
        return argv

    monkeypatch.setattr(actions, "argv_of", argv_of)
    monkeypatch.setattr(
        actions.proc,
        "tool_argv",
        lambda name, *args: ["/fake/tdd/bin/tdd-exe", name, *args],
    )
    return actions


def test_a_python_step_is_uv_run_with_its_reqs(xp_root):
    from tabsdata_dev.tool.xp import actions

    _script(xp_root, "pass\n")
    inst = _python_suite(
        xp_root, [_py("c", "scripts/check.py", "a", reqs=["polars==1.9.0", "rich"])]
    )
    argv = actions.argv_of(inst.actions[0], inst, "p")
    assert argv[:7] == [
        "uv",
        "run",
        "--no-project",
        "--with",
        "polars==1.9.0",
        "--with",
        "rich",
    ]
    assert argv[7].endswith("scripts/check.py") and argv[8:] == ["a"]


def test_a_python_step_gets_its_params_env_path_and_the_tdd_module(xp_root, launcher):
    """Run from the suite dir, params expanded, the run's names in its
    environment, tdd-exe first on its PATH and `from tdd import tdd` working."""
    from tabsdata_dev.tool.xp import work

    out = xp_root / "seen.json"
    _script(
        xp_root,
        "import json, os, sys\n"
        "from tdd import note, tdd\n"
        f"json.dump({{'argv': sys.argv[1:], 'cwd': os.getcwd(), "
        "'env': {k: os.environ[k] for k in ('XP_WORK_DIR', 'XP_PROJECT', 'XP_ID', "
        "'XP_SHORT_ID', 'XP_SUITE_RUN')}, "
        f"'path0': os.environ['PATH'].split(os.pathsep)[0]}}, open({str(out)!r}, 'w'))\n",
    )
    inst = _python_suite(
        xp_root,
        [_py("c", "scripts/check.py", "${xp:dir}/ops.jsonl", "${xp:project}")],
    )
    assert launcher.run_script(inst, "proj", launcher.Selection()) == 0
    seen = json.loads(out.read_text())
    assert seen["argv"] == [f"{work.work_dir()}/ops.jsonl", "proj"]
    assert (
        pathlib.Path(seen["cwd"]).resolve() == pathlib.Path(inst.source_dir).resolve()
    )
    assert seen["env"] == {
        "XP_WORK_DIR": str(work.work_dir()),
        "XP_PROJECT": "proj",
        "XP_ID": PH,
        "XP_SHORT_ID": "use00_000000",
        "XP_SUITE_RUN": "i",
    }
    assert seen["path0"] == "/fake/tdd/bin"


def test_a_failed_step_stops_the_run_unless_it_continues_on_fail(xp_root, launcher):
    from tabsdata_dev.tool.xp import state

    _script(xp_root, "print('row 3 differs'); raise SystemExit(1)\n", "bad.py")
    _script(xp_root, "raise SystemExit(0)\n", "good.py")
    bad = _py("bad", "scripts/bad.py")
    good = _py("good", "scripts/good.py")
    bad_goes_on = _py("bad", "scripts/bad.py", continue_on_fail=True)

    inst = _python_suite(xp_root, [bad_goes_on, good])
    assert launcher.run_script(inst, "p", launcher.Selection()) == 1  # deferred
    steps = [(s["path"], s["ok"]) for s in state.run.reporter.steps]
    assert steps[-2:] == [("scripts/bad.py", False), ("scripts/good.py", True)]

    inst = _python_suite(xp_root, [bad, good])
    with pytest.raises(state.XpError, match="(?s)python 'bad' failed.*row 3 differs"):
        launcher.run_script(inst, "p", launcher.Selection())


def test_a_python_step_says_its_note_on_a_marked_line(xp_root, launcher):
    """The last `xp-note:` line is in the note, passed or failed; unmarked
    output is not, and a failure that continues keeps saying so."""
    from tabsdata_dev.tool.xp import state

    _script(
        xp_root,
        "print('xp-note: first'); print('noise'); print('xp-note:  10/10 rows ')\n",
        "good.py",
    )
    _script(xp_root, "print('xp-note: 3/10 rows'); raise SystemExit(1)\n", "bad.py")
    _script(xp_root, "print('nothing marked')\n", "plain.py")
    inst = _python_suite(
        xp_root,
        [
            _py("good", "scripts/good.py"),
            _py("bad", "scripts/bad.py", continue_on_fail=True),
            _py("plain", "scripts/plain.py"),
        ],
    )
    assert launcher.run_script(inst, "p", launcher.Selection()) == 1
    notes = [s["note"] for s in state.run.reporter.steps[-3:]]
    assert notes == ["good; 10/10 rows", "bad; 3/10 rows; continue_on_fail", "plain"]


def test_a_steps_output_goes_to_run_log_line_by_line_under_its_label(xp_root, launcher):
    import sys

    from tabsdata_dev.tool.xp import state

    code = "print('one'); print('two')"
    inst = _python_suite(
        xp_root,
        [{"exe": {"name": "e", "program": sys.executable, "params": ["-c", code]}}],
    )
    assert launcher.run_script(inst, "p", launcher.Selection()) == 0
    log = state.run.reporter.log_path.read_text()
    assert "e | one\ne | two\n" in log


def test_what_still_runs_when_the_run_ends_is_killed(xp_root, launcher):
    """A timed-out block left running is the run's to end: its process group
    is killed, not waited for."""
    import sys
    import time

    hang = {
        "exe": {
            "name": "hang",
            "program": sys.executable,
            "params": ["-c", "import time; time.sleep(60)"],
        }
    }
    inst = _python_suite(xp_root, [_tmo("t", "0.2s", hang, stop=False)])
    started = time.monotonic()
    assert launcher.run_script(inst, "p", launcher.Selection()) == 0
    assert time.monotonic() - started < 30


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
    # Every level: a suite dir may nest one (dataquality/trends), kept out of its
    # parent's lanes.
    dirs = [d for d in sorted(root.rglob("*")) if d.is_dir()]
    files = [
        f
        for d in dirs
        if not {"functions", "scripts", "__pycache__"} & set(d.relative_to(root).parts)
        for f in suites.lane_files(d)
    ]
    assert len(files) > 100
    assert root / "dataquality" / "trends" / "mysqlcdc_airportdb.json" in files
    for f in files:
        assert build_instance("i", f).stages, f
    staged = build_instance(
        "i", root / "cdc" / "postgrescdc_initial_load_live_serial.json"
    )
    assert [s.kind for s in staged.stages] == [
        "domain-manifest",
        "actions",
        "collections",
        "functions",
        "actions",
        "sentinel",
        "actions",
        "monitor",
    ]


def _dm(*domains, emit_ops=None):
    body = {"domains": list(domains)}
    if emit_ops is not None:
        body = {"emit_ops": emit_ops, **body}
    return {"domain-manifest": body}


PG = {"name": N("pg"), "system": "postgres", "model": "world", "size": 10}
FS = {"name": N("fs"), "system": "fs"}


def test_a_domain_manifest_stage_reads_its_domains_and_emit_settings(xp_root):
    from tabsdata_dev.tool.xp.models import build_instance

    doc = [
        _dm(
            PG,
            FS,
            {**PG, "name": N("quiet"), "emit": False},
            emit_ops="${xp:dir}/o",
        )
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    [stage] = inst.stages
    assert stage.kind == "domain-manifest"
    assert [(d.name, d.system) for d in inst.domains] == [
        (f"{PH}_pg", "postgres"),
        (f"{PH}_fs", "fs"),
        (f"{PH}_quiet", "postgres"),
    ]
    dm = stage.domain_manifest
    assert dm.emit_ops == "${xp:dir}/o" and [d.emit for d in dm.domains] == [
        True,
        True,
        False,
    ]
    assert dm.domains[0].size == 10
    # a seeded domain with no size loads the base; an unseeded one has none
    unsized = {k: v for k, v in PG.items() if k != "size"}
    [seeded, bare] = (
        build_instance("j", _staged_suite(xp_root, [_dm(unsized, FS)]))
        .stages[0]
        .domain_manifest.domains
    )
    assert (seeded.size, bare.size) == (1, None)


@pytest.mark.parametrize(
    "doc, why",
    [
        ([{"domain-manifest": [PG]}], "domain-manifest takes an object"),
        ([_dm({**PG, "size": 0})], "size 0 is not a positive integer"),
        ([_dm({**PG, "size": "10"})], "valid integer"),
        ([_dm({**PG, "size": True})], "valid integer"),
        ([_dm({"name": "x", "system": "fs", "size": 1})], "size needs a model"),
        (
            [_dm({k: v for k, v in PG.items() if k != "size"} | {"data": "s"})],
            "Extra inputs",
        ),
        ([_dm(PG, emit_ops="${xp:workdir}/o")], r"\$\{xp:workdir\} is not a token"),
        ([_dm({**PG, "name_in_system": "pinned"})], "Extra inputs"),
        ([_dm(PG), {"domains": calls("pg", "fs")}], f"'{PH}_pg' is created twice"),
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
            {**PG, "name": N("quiet"), "emit": False},
            {**PG, "name": N("pg2")},
            emit_ops="${xp:dir}/ops.jsonl",
        )
    ]
    inst = build_instance("i", _staged_suite(xp_root, doc))
    final = work.work_dir() / "ops.jsonl"
    final.write_text("earlier\n")
    domains.create_from_manifest(inst, inst.stages[0].domain_manifest, 1)
    by = {e["name"][len(PH) + 1 :]: e for e in seen["entries"]}
    assert set(by) == {"pg", "fs", "quiet", "pg2"}
    assert "emit-ops" not in by["fs"] and "emit-ops" not in by["quiet"]
    assert by["pg"]["emit-ops"] != by["pg2"]["emit-ops"]  # one file each
    assert by["pg"]["size"] == 10 and by["pg"]["name-in-system"] == "use00_000000_pg"
    assert final.read_text() == f"earlier\n{PH}_pg\n{PH}_pg2\n"


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
    assert [e["name"] for e in seen] == [f"{PH}_pg"] and "emit-ops" not in seen[0]


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


def test_a_suite_run_is_named_by_its_xp_id_and_reused_when_named_again(xp_root, capsys):
    from tabsdata_dev.tool.xp import pointers

    assert _run(["create-instance", "--suite", "demo/one", *_suites_dir(xp_root)]) == 0
    assert pointers.ids_of(XP_ID) == (XP_ID, XP_SHORT)
    # named again: the same run, its IDs kept -- how a failed run is finished
    args = ["create-instance", "--suite", "demo/one", *_suites_dir(xp_root)]
    assert _run([*args, "--suite-run", XP_ID]) == 0
    assert pointers.ids_of(XP_ID) == (XP_ID, XP_SHORT)
    assert "reusing it, and its XP_ID" in capsys.readouterr().err
    # ...but never repointed at another suite
    rc = _run(
        [
            "create-instance",
            "--suite",
            "demo/two",
            *_suites_dir(xp_root),
            "--suite-run",
            XP_ID,
        ]
    )
    assert rc == 1 and f"suite run '{XP_ID}' exists for" in capsys.readouterr().err


def test_a_suite_dirs_lanes_are_suite_runs_with_ids_of_their_own(xp_root):
    from tabsdata_dev.tool.xp import pointers

    assert (
        _run(
            [
                "create-instance",
                "--suite",
                "demo",
                *_suites_dir(xp_root),
                "--suite-run",
                "g",
            ]
        )
        == 0
    )
    assert pointers.instance_group("g") == ["g_one", "g_two"]
    assert pointers.ids_of("g")[0] == XP_ID
    assert pointers.ids_of("g_one")[0] == "xp_tucu_0_20261001T093013"
    assert pointers.ids_of("g_two")[0] == "xp_tucu_0_20261001T093014"
    one = pointers.load_instance("g_one")
    assert one.domains[0].name == "xp_tucu_0_20261001T093013_fs"


def test_the_project_is_the_runs_xp_id_and_suite_unless_named(xp_root, capsys):
    rc = _run(["one-shot", "--suite", "demo/one", *_suites_dir(xp_root), "--dry-run"])
    out, err = capsys.readouterr()
    assert rc == 0, err
    assert f"tdd tdk project create --name {XP_ID}_demo_one" in out
    assert f"xp id {XP_ID}, short id {XP_SHORT}" in err


def test_a_project_that_is_not_the_runs_is_refused_unless_forced(xp_root, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import pointers, project, shell, state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(shell, "project_exists", lambda p: True)
    deleted = []
    monkeypatch.setattr(project, "delete_project", lambda p, force: deleted.append(p))
    with pytest.raises(state.XpError, match="exists and is not suite run 'r''s"):
        project.claim_project("p", "r", force=False)
    # this run's own: continued, as a rerun after a failure is
    pointers.write_project("p", "r")
    project.claim_project("p", "r", force=False)
    assert deleted == []
    # someone else's, forced: deleted, so it is made again from nothing
    project.claim_project("p", "other", force=True)
    assert deleted == ["p"]


def test_run_suite_leaves_the_suite_as_it_resolved_it(xp_root, capsys):
    from tabsdata_dev.tool.xp import state

    assert _run(["create-instance", "--suite", "demo/one", *_suites_dir(xp_root)]) == 0
    assert _run(["run-suite", "--suite-run", XP_ID, "--dry-run"]) == 0
    capsys.readouterr()
    resolved = pathlib.Path(state.run.summary["scratch"]) / "suite.resolved.json"
    doc = json.loads(resolved.read_text())
    assert doc[0]["domains"][0]["name"] == f"{XP_ID}_fs"
    assert doc[1]["collections"][0]["domains"] == {"D0": f"{XP_ID}_world"}


def _fake_tdd_exe(bin_dir: pathlib.Path) -> None:
    """A tdd-exe that echoes its arguments, and fails on `boom`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "tdd-exe"
    exe.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = boom ]; then echo "it broke" >&2; exit 3; fi\n'
        'echo "args: $*"\n'
    )
    exe.chmod(0o755)


def test_the_tdd_module_runs_tdd_exe_and_says_how_it_failed(tmp_path, monkeypatch):
    """`from tdd import tdd`, as a python step has it: `tdd()` is tdd-exe, its
    output back and its failure a TddError carrying status and what it said."""
    import os
    import subprocess
    import sys

    from tabsdata_dev.tool.xp import actions

    _fake_tdd_exe(tmp_path / "bin")
    script = tmp_path / "check.py"
    script.write_text(
        "from tdd import tdd, note, TddError\n"
        "print(tdd('pqt', 'csv', 'f.parquet').strip())\n"
        "try:\n"
        "    tdd('boom')\n"
        "except TddError as exc:\n"
        "    print('failed', exc.status, exc.output.strip())\n"
        "note('812 rows,\\n  3 rows/s')\n"
    )
    env = {
        **os.environ,
        "PATH": f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}",
        "PYTHONPATH": str(actions.tdd_module_dir()),
    }
    done = subprocess.run(
        [sys.executable, str(script)], env=env, capture_output=True, text=True
    )
    assert done.returncode == 0, done.stderr
    assert done.stdout.splitlines() == [
        "args: pqt csv f.parquet",
        "failed 3 it broke",
        "xp-note: 812 rows, 3 rows/s",
    ]
    # its directory holds it alone: nothing else lands on a step's path
    assert [
        p.name for p in actions.tdd_module_dir().iterdir() if p.suffix == ".py"
    ] == ["tdd.py"]


def test_the_tdd_module_is_standard_library_only():
    """It runs in whatever environment a step's reqs make, so it imports
    nothing else."""
    import ast

    from tabsdata_dev.tool.xp import actions

    tree = ast.parse((actions.tdd_module_dir() / "tdd.py").read_text())
    imported = {
        (node.module or "").split(".")[0]
        if isinstance(node, ast.ImportFrom)
        else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"__future__", "subprocess", "sys", "pathlib"}, imported


@pytest.mark.parametrize(
    "old, new",
    [
        ("${xp_name(pg)}", "${xp:name(NAME)}"),
        ("${XP_ID}", "${xp:id}"),
        ("${XP_SHORT_ID}", "${xp:short_id}"),
        ("${XP_WORK_DIR}/ops.jsonl", "${xp:dir}"),
        ("${XP_PROJECT}", "${xp:project}"),
    ],
)
def test_an_older_tokens_spelling_is_refused_naming_the_one_it_is_now(old, new):
    from tabsdata_dev.tool.xp import ids

    with pytest.raises(ValueError, match=re.escape(f"is {new} now")):
        ids.resolve([old], XP_ID, XP_SHORT)
    with pytest.raises(ValueError, match=re.escape("a token is ${xp:...} now")):
        ids.resolve(["${XP_NOPE}"], XP_ID, XP_SHORT)


def test_a_runs_summary_counts_every_phases_lane_steps_and_its_lanes_once(tmp_path):
    """A one-shot over a suite dir dispatches its lanes in phases -- run-suite,
    destroy-project, destroy-domains -- each naming a lane its own way (a
    project's name, a suite run's). Each phase's steps count; the lanes are
    the suite dir's."""
    from tabsdata_dev.tool.xp.reporter import Reporter, render_summary

    r = Reporter("demo", "one-shot", "x", tmp_path)
    for lane in ("p_one", "p_two"):
        r.absorb_lane("run-suite", lane, {"steps": 10, "failed": 0})
        r.absorb_lane("destroy-project", lane, {"steps": 3, "failed": 0})
    for lane in ("r_one", "r_two"):
        r.absorb_lane("destroy-domains", lane, {"steps": 2, "failed": 1})
    doc = r.summary()
    assert (doc["lanes_total"], doc["lane_steps"], doc["lane_failed"]) == (2, 30, 2)
    assert (
        " - summary - 30 step(s) over 2 lane(s), 28 ok, 2 failed in "
        in render_summary(doc)
    )


def test_td_profile_is_the_runs_profile_name_or_no_option(xp_root, monkeypatch):
    """`${td:profile}` in a tdd, exe or python step's options or params is the
    run's profile name -- a suite writes `"--profile", "${td:profile}"` on the
    steps that call tdk. A run with no profile drops the option, pair or
    `--profile=` form alike: tdk refuses `--profile ""`. Elsewhere in an argument
    the token is "". Any other `${td:...}`, or the token in a domain call, is
    refused when the suite is read."""
    from tabsdata_dev.tool.xp import actions, models, state

    fn = {
        "tdd": {
            "name": "off",
            "tool": "tdk",
            "command": "fn",
            "options": [
                "disable",
                "--proj",
                "${xp:project}",
                "--profile",
                "${td:profile}",
            ],
        }
    }
    check = {
        "python": {
            "name": "check",
            "script": "scripts/check.py",
            "params": [
                "${xp:dir}/ops.jsonl",
                "--profile=${td:profile}",
                "--label=p${td:profile}",
            ],
        }
    }
    _script(xp_root, "pass\n")
    inst = _python_suite(xp_root, [fn, check])
    off, chk = inst.actions

    monkeypatch.setattr(state.run, "profile", None)
    assert actions.argv_of(off, inst, "P")[-3:] == ["disable", "--proj", "P"]
    unprofiled = actions.argv_of(chk, inst, "P")
    assert unprofiled[-2].endswith("/ops.jsonl") and unprofiled[-1] == "--label=p"
    monkeypatch.setattr(state.run, "profile", "dev")
    assert actions.argv_of(off, inst, "P")[-2:] == ["--profile", "dev"]
    assert actions.argv_of(chk, inst, "P")[-2:] == ["--profile=dev", "--label=pdev"]

    with pytest.raises(Exception, match=r"\$\{td:conn\} is not a token"):
        _python_suite(xp_root, [{"tdd": dict(fn["tdd"], options=["${td:conn}"])}])
    with pytest.raises(ValueError, match="for a tdd, exe or python step"):
        models._refuse_unknown_tokens("${td:profile}", "domain call")


def _fake_one_shots(monkeypatch, fail=()):
    """Each selector's `tdd xp one-shot` child replaced by a script that echoes
    its words and exits 1 for the selectors in `fail`."""
    import sys

    from tabsdata_dev.tool.xp import batch, shell

    monkeypatch.setenv("_TDD_CRYPTO_KEY", "k")
    monkeypatch.delenv("TDD_PARALLELISM", raising=False)
    monkeypatch.setattr(shell, "require_login", lambda: None)
    script = f"import sys; print('ran', *sys.argv[1:]); sys.exit(sys.argv[3] in {list(fail)!r})"
    monkeypatch.setattr(
        batch, "child_argv", lambda *words: [sys.executable, "-c", script, *words]
    )


def _second_suite_dir(xp_root):
    (xp_root / "suites" / "other").mkdir()
    (xp_root / "suites" / "other" / "a.json").write_text(json.dumps([MONITOR]))
    (xp_root / "suites" / "empty").mkdir()
    (xp_root / "suites" / "empty" / "notes.json").write_text(
        json.dumps({"_comment": "not a suite"})
    )


def test_one_shot_ALL_runs_every_suite_dir_one_at_a_time(
    xp_root, monkeypatch, capsys, tmp_path
):
    """ALL is every suite dir holding a definition, each a one-shot child of its
    own, one after another: they all provision on the same systems and instance.
    The selection options reach every child; the batch writes the report."""
    from tabsdata_dev.tool.xp import batch

    _fake_one_shots(monkeypatch)
    _second_suite_dir(xp_root)
    report = tmp_path / "report.json"
    rc = _run(
        ["one-shot", "--suite", "ALL", *_suites_dir(xp_root)]
        + ["--tags", "smoke", "--keep", "--report", str(report)]
    )
    seen = capsys.readouterr()
    text = seen.out + seen.err
    assert rc == 0, text
    assert "2 suite selector(s), one at a time: demo, other" in text
    root = (xp_root / "suites").resolve()
    assert (
        f"[demo] ran one-shot --suite demo --suites-dir {root} --tags smoke --keep"
        in text
    )
    assert "[other] ran one-shot --suite other" in text and "empty" not in text
    doc = json.loads(report.read_text())
    assert [t["name"] for t in doc["tasks"]] == ["demo", "other"]
    assert doc["parallelism"] == 1 and doc["ok"] == 2

    monkeypatch.setenv("TDD_PARALLELISM", "4")
    assert batch._workers(2) == 2 and batch._workers(9) == 4


def test_one_shot_list_reports_failures_and_fail_fast_starts_no_more(
    xp_root, monkeypatch, capsys
):
    _fake_one_shots(monkeypatch, fail=("demo",))
    _second_suite_dir(xp_root)

    rc = _run(["one-shot", "--suite", "demo,other", *_suites_dir(xp_root)])
    seen = capsys.readouterr()
    assert rc == 1
    assert "1 of 2 suite selector(s) failed: demo" in seen.err
    assert "[other] ran one-shot --suite other" in seen.out

    rc = _run(
        ["one-shot", "--suite", "demo,other", *_suites_dir(xp_root), "--fail-fast"]
    )
    seen = capsys.readouterr()
    assert rc == 1
    assert "not run after the failure: other" in seen.err
    assert "[other] ran" not in seen.out


def test_one_shot_list_refuses_a_shared_run_and_unknown_selectors_up_front(
    xp_root, monkeypatch, capsys
):
    """A suite run or project names one run, which many selectors cannot share;
    a mistyped selector stops the batch before any child starts."""
    from tabsdata_dev.tool.xp import batch

    _fake_one_shots(monkeypatch)
    rc = _run(["one-shot", "--suite", "ALL", *_suites_dir(xp_root), "--project", "p"])
    assert rc == 1
    assert "--project names a single suite run" in capsys.readouterr().err

    rc = _run(["one-shot", "--suite", "demo,nope", *_suites_dir(xp_root)])
    seen = capsys.readouterr()
    assert rc == 1 and "nope" in seen.err and "[demo] ran" not in seen.out

    assert not batch.is_batch("demo") and not batch.is_batch("demo/one")
    assert batch.is_batch("all") and batch.is_batch("demo, other")
    assert not batch.is_batch("demo,demo")


def _seq_instance(xp_root, name, systems=(), seq=None):
    from tabsdata_dev.tool.xp import models

    doc = [
        *([{"seq": seq}] if seq is not None else []),
        *(
            [
                {
                    "domain-manifest": {
                        "domains": [
                            {"name": f"{name}_{s}", "system": s} for s in systems
                        ]
                    }
                }
            ]
            if systems
            else []
        ),
        MONITOR,
    ]
    path = xp_root / "suites" / "demo" / f"{name}.json"
    path.write_text(json.dumps(doc))
    return models.build_instance(name, path)


def test_a_suite_declares_its_seq_as_a_name_or_a_list(xp_root):
    assert _seq_instance(xp_root, "a", seq="salesforce").seq == ["salesforce"]
    assert _seq_instance(xp_root, "b", seq=["x", "y", "x"]).seq == ["x", "y"]
    assert _seq_instance(xp_root, "c").seq == []
    assert [s.kind for s in _seq_instance(xp_root, "d", seq="x").stages] == ["monitor"]


@pytest.mark.parametrize("bad", ["", [], [""], [1], {"a": 1}])
def test_a_malformed_seq_is_refused(xp_root, bad):
    from tabsdata_dev.tool.xp import state

    with pytest.raises(state.XpError, match="seq takes a name or a list of names"):
        _seq_instance(xp_root, "bad", seq=bad)


def test_a_lanes_groups_are_its_seq_and_its_exclusive_systems(xp_root, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import project, seq, state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(project, "exclusive_systems", lambda: {"salesforce"})
    groups = seq.groups(
        {
            "report": _seq_instance(xp_root, "r", systems=["salesforce", "dev"]),
            "soql": _seq_instance(xp_root, "s", systems=["salesforce"], seq="crm"),
            "files": _seq_instance(xp_root, "f", systems=["s3"]),
        }
    )
    assert groups == {
        "report": frozenset({"salesforce"}),
        "soql": frozenset({"salesforce", "crm"}),
        "files": frozenset(),
    }


def test_lanes_of_one_seq_never_run_together_while_the_rest_run_beside_them(
    monkeypatch,
):
    import threading
    import time

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import lanes, state

    monkeypatch.setenv("TDD_PARALLELISM", "4")
    state.bind(render.Renderer(state.TOOL), argparse_ns())
    guard = threading.Lock()
    running: set[str] = set()
    overlaps: list[set[str]] = []

    def run_lane(item):
        lane, _ = item
        with guard:
            running.add(lane)
            overlaps.append(set(running))
        time.sleep(0.05)
        with guard:
            running.discard(lane)

    sf = frozenset({"salesforce"})
    argvs = [(name, []) for name in ("sf1", "sf2", "sf3", "a", "b")]
    groups = {"sf1": sf, "sf2": sf, "sf3": sf}
    lanes.run_in_sequence(argvs, groups, run_lane, lambda: False)
    assert {lane for seen in overlaps for lane in seen} == {
        "sf1",
        "sf2",
        "sf3",
        "a",
        "b",
    }
    assert all(len(seen & {"sf1", "sf2", "sf3"}) <= 1 for seen in overlaps)
    assert any({"a", "b"} <= seen for seen in overlaps)


def test_a_lane_child_is_handed_its_groups(monkeypatch, capsys):
    import sys

    from tabsdata_dev.common.core import render
    from tabsdata_dev.tool.xp import lanes, state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    child = (
        "import json, os; print(json.dumps({'command': 'xp', 'event': 'ok', "
        "'xp': 'summary', 'message': os.environ.get('_TDD_XP_SEQ', 'unset')}))"
    )
    seen = []
    real = lanes.rep

    def absorbing(label, lane, summary):
        seen.append((lane, summary["message"]))

    monkeypatch.setattr(real(), "absorb_lane", absorbing)
    failed = lanes.dispatch(
        "t",
        [
            ("one", [sys.executable, "-c", child]),
            ("two", [sys.executable, "-c", child]),
        ],
        fatal=False,
        groups={"one": frozenset({"salesforce", "crm"})},
    )
    assert failed == []
    assert sorted(seen) == [("one", "crm,salesforce"), ("two", "")]


def test_a_lane_holds_the_lock_of_each_group_it_was_handed(xp_root, monkeypatch):
    import os

    from tabsdata_dev.common.core import filelock, render
    from tabsdata_dev.tool.xp import project, seq, state

    state.bind(render.Renderer(state.TOOL), argparse_ns())
    monkeypatch.setattr(
        project, "exclusive_systems", lambda: pytest.fail("store asked again")
    )
    monkeypatch.setenv(state.SEQ_ENV, "salesforce,crm")
    inst = _seq_instance(xp_root, "held", systems=["salesforce"])
    with seq.held(inst):
        for name in ("salesforce", "crm"):
            fd = os.open(seq.lock_file(name), os.O_RDWR)
            try:
                assert not filelock.try_lock(fd)
            finally:
                os.close(fd)
    for name in ("salesforce", "crm"):
        with filelock.held(seq.lock_file(name)):
            pass
    assert state.SEQ_ENV not in os.environ
