#
# Copyright 2026 Tabsdata Inc.
#

import os
import shutil
import subprocess
import sys

import pytest

from tabsdata_dev.tool import jq


def _exe(path, script: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(script)
    path.chmod(0o755)


def test_runs_the_paths_jq_never_itself(tmp_path, monkeypatch, capfd):
    """The launcher's own entry point is `jq` in this venv's scripts dir, first
    on PATH under tdd: it is skipped, or the launcher would run itself."""
    own = tmp_path / "venv" / "bin"
    _exe(own / "jq", "#!/bin/sh\necho launcher; exit 3\n")
    _exe(tmp_path / "sys" / "jq", '#!/bin/sh\necho "jq got: $*"\n[ "$1" != fail ]\n')
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


def test_refuses_when_the_machine_has_no_jq(tmp_path, monkeypatch, capsys):
    own = tmp_path / "venv" / "bin"
    _exe(own / "jq", "#!/bin/sh\n")
    monkeypatch.setattr(sys, "executable", str(own / "python"))
    monkeypatch.setenv("PATH", str(own))
    monkeypatch.setattr("sys.argv", ["jq"])
    assert jq.main() == 1
    assert "jq is not installed: not found on PATH" in capsys.readouterr().err


@pytest.mark.skipif(shutil.which("jq") is None, reason="no jq on this machine")
def test_stdin_reaches_the_real_jq(tmp_path):
    """Filtering stdin is what jq is for: the launcher passes it through."""
    code = "import sys; from tabsdata_dev.tool import jq; sys.exit(jq.main())"
    done = subprocess.run(
        [sys.executable, "-c", code, "-c", ".a"],
        input='{"a": [1, 2]}',
        capture_output=True,
        text=True,
        env={k: v for k, v in os.environ.items() if k != "_TDD_TOOL"},
    )
    assert done.returncode == 0 and done.stdout == "[1,2]\n"
