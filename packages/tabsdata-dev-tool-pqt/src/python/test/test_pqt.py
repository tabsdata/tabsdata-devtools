#
# Copyright 2026 Tabsdata Inc.
#

import pathlib
import sys

from tabsdata_dev.tool import pqt


def _fake_venv(tmp_path, monkeypatch, script: str) -> pathlib.Path:
    """A venv whose scripts dir holds a parquet-tools; only the interpreter's
    directory is what the launcher reads."""
    bin_dir = tmp_path / "venv" / "bin"
    bin_dir.mkdir(parents=True)
    exe = bin_dir / "parquet-tools"
    exe.write_text(script)
    exe.chmod(0o755)
    monkeypatch.setattr(sys, "executable", str(bin_dir / "python"))
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    return bin_dir


def test_every_argument_reaches_parquet_tools(tmp_path, monkeypatch, capfd):
    _fake_venv(
        tmp_path, monkeypatch, '#!/bin/sh\necho "pqt got: $*"\n[ "$1" != fail ]\n'
    )
    monkeypatch.setattr("sys.argv", ["pqt", "show", "--help", "--format", "json"])
    assert pqt.main() == 0
    assert "pqt got: show --help --format json" in capfd.readouterr().out
    monkeypatch.setattr("sys.argv", ["pqt", "fail"])
    assert pqt.main() == 1
    out, err = capfd.readouterr()
    assert "pqt got: fail" in out and "parquet-tools exited with status 1" in err


def test_parquet_tools_is_the_toolsets_not_the_paths(tmp_path, monkeypatch, capsys):
    """Pinned means this venv's: one elsewhere on PATH does not stand in."""
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    (elsewhere / "parquet-tools").write_text("#!/bin/sh\n")
    (elsewhere / "parquet-tools").chmod(0o755)
    empty = tmp_path / "venv" / "bin"
    empty.mkdir(parents=True)
    monkeypatch.setattr(sys, "executable", str(empty / "python"))
    monkeypatch.setenv("PATH", str(elsewhere))
    monkeypatch.setattr("sys.argv", ["pqt"])
    assert pqt.main() == 1
    assert "parquet-tools is not installed" in capsys.readouterr().err


def test_the_toolset_really_has_parquet_tools(monkeypatch, capfd):
    """The pin in deps-xp is what provides it: run the real one."""
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    monkeypatch.setattr("sys.argv", ["pqt", "--help"])
    assert pqt.main() == 0
    assert "csv" in capfd.readouterr().out
