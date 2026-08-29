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
    monkeypatch.delenv("TDD_XP_SCRATCH", raising=False)
    return root


def _run(argv):
    from tabsdata_dev.tool import xp_run

    return xp_run.cli.run(
        xp_run.NAME,
        xp_run.DESCRIPTION,
        xp_run.body,
        argv=argv,
        configure=xp_run.configure,
    )


def test_suite_paths_resolve_to_a_file_or_to_lanes(xp_root):
    from tabsdata_dev.tool.xp_run import suites

    one = xp_root / "suites" / "demo" / "one.json"
    assert suites.resolve(str(one)) == (one, None)
    assert suites.resolve(str(one.with_suffix("")))[0] == one  # .json tolerated
    path, lanes = suites.resolve(str(xp_root / "suites" / "demo"))
    assert path == xp_root / "suites" / "demo" and [p.stem for p in lanes] == [
        "one",
        "two",
    ]
    assert suites.label(one) == "demo/one" and suites.label(path) == "demo"
    assert (
        suites.token(one) == "demo_one"
        and suites.token(one.with_name("suite.json")) == "demo"
    )
    assert suites.base_dir(one.parent) == xp_root  # the ancestor holding connections/
    rows = suites.list_suites(xp_root / "suites")
    assert [r["suite"] for r in rows] == ["demo/one", "demo/two"] and rows[0][
        "triggers"
    ] == 4


def test_pointers_live_under_the_tdd_data_dir(xp_root, tmp_path):
    from tabsdata_dev.tool.xp_run import pointers, suites

    one = xp_root / "suites" / "demo" / "one.json"
    pointers.write_instance("i1", one)
    assert pointers.store() == tmp_path / "tdd" / "data" / "xp-run"
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
    from tabsdata_dev.tool.xp_run import project
    from tabsdata_dev.tool.xp_run.models import build_instance

    inst = build_instance("i", xp_root / "suites" / "demo" / "one.json")
    batches = [[t.function for t in b] for b in project.trigger_batches(inst.triggers)]
    assert batches == [["pub", "pub2"], ["tfr"], ["pub3"]]


def test_connection_prep_resolves_secrets_and_interpolates(xp_root, monkeypatch):
    from tabsdata_dev.tool.xp_run import conn, state

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
    from tabsdata_dev.tool.xp_run import domains
    from tabsdata_dev.tool.xp_run.models import build_instance

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


def test_dry_run_oneshot_prints_the_tdd_commands_and_touches_no_server(xp_root, capsys):
    one = xp_root / "suites" / "demo" / "one.json"
    rc = _run(["oneshot", "--suite", str(one), "--project", "p", "--dry-run"])
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
    one = xp_root / "suites" / "demo" / "one.json"
    rc = _run(
        ["create-instance", "--suite", str(one), "--instance", "i2", "--format", "json"]
    )
    assert rc == 0
    rc = _run(["run-project", "--project", "nope", "--dry-run", "--format", "json"])
    out, _ = capsys.readouterr()
    events = [json.loads(line) for line in out.splitlines()]
    assert all(e["command"] == "xp-run" for e in events)
    assert (
        events[-1]["event"] == "error"
        and "project 'nope' not found" in events[-1]["message"]
    )
    assert rc == 1


def test_bench_rejects_a_single_file_and_list_suites_reports(xp_root, capsys):
    one = xp_root / "suites" / "demo" / "one.json"
    assert _run(["bench", "--suite", str(one), "--dry-run"]) == 1
    assert "bench needs a suite DIR" in capsys.readouterr().err
    assert (
        _run(["list-suites", "--suite", str(xp_root / "suites"), "--format", "json"])
        == 0
    )
    last = json.loads(capsys.readouterr().out.splitlines()[-1])
    assert last["event"] == "ok" and [s["suite"] for s in last["suites"]] == [
        "demo/one",
        "demo/two",
    ]
