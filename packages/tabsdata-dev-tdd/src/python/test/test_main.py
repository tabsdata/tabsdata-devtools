#
# Copyright 2026 Tabsdata Inc.
#

import json

from tabsdata_dev.tdd import __main__ as main_mod
from tabsdata_dev.tdd import render


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_version_is_an_ok_event(capsys):
    assert main_mod.main(["--format", "json", "--version"]) == 0
    (event,) = _events(capsys)
    assert event["command"] == "tdd" and event["event"] == "ok"
    assert event["message"] == f"tdd {event['version']}"


def test_bad_format_is_an_error_with_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert main_mod.main(["--format", "xml", "--version"]) == 1
    assert "--format must be json or view" in capsys.readouterr().err


def test_uninitialized_dir_is_an_error_event(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert (
        main_mod.main(["--dir", str(tmp_path / "nope"), "--format=json", "info"]) == 1
    )
    (event,) = _events(capsys)
    assert event["event"] == "error" and "not initialized" in event["message"]
    assert event["log"].startswith(str(tmp_path))


def test_builtins_take_format_after_the_word(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert (
        main_mod.main(["--dir", str(tmp_path / "nope"), "doctor", "--format", "json"])
        == 1
    )
    assert _events(capsys)[0]["command"] == "doctor"


def test_builtins_reject_other_arguments(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert main_mod.main(["--format=json", "info", "--bogus"]) == 1
    assert "takes no argument" in _events(capsys)[0]["message"]


def test_reqs_reports_every_declaration(capsys):
    code = main_mod.main(["--format", "json", "--reqs"])
    events = _events(capsys)
    assert events[-1]["event"] in ("ok", "error")
    assert (code == 0) == (events[-1]["event"] == "ok")
    assert any(e["event"] == "info" and e.get("binary") == "jq" for e in events)


def test_tdd_install_help_and_usage_errors():
    from tabsdata_dev.tdd import install

    assert install.main(["--help"]) == 0


def test_tdd_install_usage_error_is_an_event(tmp_path, monkeypatch, capsys):
    from tabsdata_dev.tdd import install

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert install.main(["--bogus", "--format", "json"]) == 1
    (event,) = _events(capsys)
    assert event["command"] == "tdd-install" and event["event"] == "error"
    assert install.main(["--format", "xml"]) == 1


def test_generate_entry_point_reports_as_events(tmp_path, monkeypatch, capsys):
    from tabsdata_dev.tdd import generate

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert generate.main(["--bogus"]) == 1
    assert generate.main(["--help"]) == 0
