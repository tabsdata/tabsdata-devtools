#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.tool import demo_exe2


def test_prints_its_name(capsys):
    assert demo_exe2.main() == 0
    assert capsys.readouterr().out == "demo-exe2\n"


def test_pins_are_the_demo_env2_toolset():
    # Proves the tool runs in its own toolset's env: demo-env1 and demo-env2 pin
    # packaging differently, and this test must see only its own pin.
    from importlib.metadata import version

    assert version("packaging").startswith("25.")
