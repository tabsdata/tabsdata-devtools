#
# Copyright 2026 Tabsdata Inc.
#

import pathlib
import subprocess
import sys
from importlib import metadata

from tabsdata_dev.tool import twine as tool


def _script(dist: str) -> str:
    (ep,) = [e for e in metadata.distribution(dist).entry_points if e.name == "twine"]
    return ep.value


def test_the_tools_entry_point_is_twines_own():
    """Both distributions write bin/twine into one venv; only identical entry
    points make the install order irrelevant."""
    assert _script("tabsdata-dev-tool-twine") == tool.ENTRY_POINT
    assert _script("twine") == tool.ENTRY_POINT


def test_the_toolset_runs_the_pinned_twine():
    """`tdd twine` execs the venv's bin/twine: the pin in deps-twine."""
    exe = pathlib.Path(sys.executable).parent / "twine"
    done = subprocess.run([exe, "--version"], capture_output=True, text=True)
    assert done.returncode == 0
    assert f"twine version {metadata.version('twine')}" in done.stdout
    assert metadata.version("twine") == "7.0.0"
