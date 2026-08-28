#
# Copyright 2026 Tabsdata Inc.
#

import json

from tabsdata_dev.tool import domain


def test_help_is_an_ok_event_with_the_verbs(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["domain", "--format", "json", "--help"])
    assert domain.main() == 0
    event = json.loads(capsys.readouterr().out)
    assert event["event"] == "ok" and event["command"] == "domain"
    assert any(c["name"] == "create" for c in event["commands"])


def test_unknown_verb_is_an_error(monkeypatch, capsys, tmp_path):
    from tabsdata_dev.common.core import render

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    monkeypatch.setattr("sys.argv", ["domain", "nope", "--format", "json"])
    assert domain.main() == 1
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "error"
