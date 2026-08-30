#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.tool import km


def test_requires_a_venv_activated_with_tdd_venv(monkeypatch, capsys):
    monkeypatch.delenv("TDD_VENV", raising=False)
    monkeypatch.setattr("sys.argv", ["km", "--help"])
    assert km.main() == 1
    err = capsys.readouterr().err
    assert "TDD_VENV" in err and "tdd venv" in err


def test_every_argument_reaches_the_program(tmp_path, monkeypatch, capfd):
    root = tmp_path / "managed-venvs"
    exe = root / "pyenv" / "v1" / "bin" / "km"
    exe.parent.mkdir(parents=True)
    (root / "v1.env").write_text("pyenv\n")
    exe.write_text('#!/bin/sh\necho "km got: $*"\n[ "$1" != fail ]\n')
    exe.chmod(0o755)
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("TDD_VENV", "v1")
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    # --help, --format, --version, -- : none of them is the launcher's
    monkeypatch.setattr(
        "sys.argv", ["km", "--help", "--format", "json", "--version", "--", "-v"]
    )
    assert km.main() == 0
    assert "km got: --help --format json --version -- -v" in capfd.readouterr().out
    monkeypatch.setattr("sys.argv", ["km", "fail"])
    assert km.main() == 1
    out, err = capfd.readouterr()
    assert "km got: fail" in out and "km exited with status 1" in err


def test_refuses_when_the_program_is_missing_from_the_venv(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "managed-venvs"
    (root / "uv" / "v2").mkdir(parents=True)
    (root / "v2.env").write_text("uv\n")
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("TDD_VENV", "v2")
    monkeypatch.setattr("sys.argv", ["km"])
    assert km.main() == 1
    assert "not installed in managed venv v2" in capsys.readouterr().err
