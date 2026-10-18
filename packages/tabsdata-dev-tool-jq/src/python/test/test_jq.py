#
# Copyright 2026 Tabsdata Inc.
#

import os
import pathlib
import shutil
import subprocess
import sys

import pytest

from tabsdata_dev.tool import jq


def _exe(path, source) -> None:
    """Install the resource script `source` as the executable `path`."""
    path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(source, path)
    path.chmod(0o755)


def test_runs_the_paths_jq_never_itself(
    tmp_path,
    monkeypatch,
    capfd,
    resource_folder,
):
    """The launcher's own entry point is `jq` in this venv's scripts dir, first
    on PATH under tdd: it is skipped, or the launcher would run itself."""
    own = tmp_path / "venv" / "bin"
    _exe(own / "jq", resource_folder / "launcher_itself.sh")
    _exe(tmp_path / "sys" / "jq", resource_folder / "echo_args.sh")
    monkeypatch.setattr(sys, "executable", str(own / "python"))
    monkeypatch.setenv("PATH", f"{own}:{tmp_path / 'sys'}")
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    monkeypatch.setattr("sys.argv", ["jq", "-r", ".a", "--help"])
    assert jq.main() == 0
    assert "jq got: -r .a --help" in capfd.readouterr().out
    monkeypatch.setattr("sys.argv", ["jq", "fail"])
    assert jq.main() == 1
    out, err = capfd.readouterr()
    assert "jq got: fail" in out and "jq exited with status 1" in err


def test_refuses_when_the_machine_has_no_jq(
    tmp_path,
    monkeypatch,
    capsys,
    resource_folder,
):
    own = tmp_path / "venv" / "bin"
    _exe(own / "jq", resource_folder / "does_nothing.sh")
    monkeypatch.setattr(sys, "executable", str(own / "python"))
    monkeypatch.setenv("PATH", str(own))
    monkeypatch.setattr("sys.argv", ["jq"])
    assert jq.main() == 1
    assert "jq is not installed: not found on PATH" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("jq") is None, reason="no jq on this machine")
def test_stdin_reaches_the_real_jq(tmp_path):
    """Filtering stdin is what jq is for: the launcher passes it through. Run
    as installed: this venv's own `jq` entry point."""
    launcher = pathlib.Path(sys.executable).parent / "jq"
    done = subprocess.run(
        [launcher, "-c", ".a"],
        input='{"a": [1, 2]}',
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "_TDD_TOOL"},
    )
    assert done.returncode == 0 and done.stdout == "[1,2]\n"
