#
# Copyright 2026 Tabsdata Inc.
#

import json

from tabsdata_dev.tool import demo_exe2


def test_prints_its_name(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["demo-exe2"])
    assert demo_exe2.main() == 0
    assert capsys.readouterr().out == "demo-exe2\n"


def test_json_carries_the_command_name(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["demo-exe2", "--format", "json", "-v"])
    assert demo_exe2.main() == 0
    lines = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [line["event"] for line in lines] == ["debug", "ok"]
    assert all(line["command"] == "demo-exe2" for line in lines)


def test_pins_are_the_demo_env2_toolset():
    # Proves the tool runs in its own toolset's env: demo-env1 and demo-env2 pin
    # packaging differently, and this test must see only its own pin.
    from importlib.metadata import version

    assert version("packaging").startswith("25.")
