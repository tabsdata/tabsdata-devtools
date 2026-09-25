#
# Copyright 2026 Tabsdata Inc.
#

from tabsdata_dev.tool import tdk


def test_requires_a_venv_activated_with_tdd_venv(monkeypatch, capsys):
    monkeypatch.delenv("_TDD_VENV", raising=False)
    # and nothing for `adopted` to find either: the developer running this may
    # well have a managed venv of their own active
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("sys.argv", ["tdk", "--help"])
    assert tdk.main() == 1
    err = capsys.readouterr().err
    assert "_TDD_VENV" in err and "tdd venv" in err


def test_every_argument_reaches_the_program(tmp_path, monkeypatch, capfd):
    root = tmp_path / "managed-venvs"
    exe = root / "pyenv" / "v1" / "bin" / "tdk"
    exe.parent.mkdir(parents=True)
    (root / "v1.json").write_text('{"manager": "pyenv"}\n')
    exe.write_text('#!/bin/sh\necho "tdk got: $*"\n[ "$1" != fail ]\n')
    exe.chmod(0o755)
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_VENV", "v1")
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    # --help, --format, --version, -- : none of them is the launcher's
    monkeypatch.setattr(
        "sys.argv", ["tdk", "--help", "--format", "json", "--version", "--", "-v"]
    )
    assert tdk.main() == 0
    assert "tdk got: --help --format json --version -- -v" in capfd.readouterr().out
    monkeypatch.setattr("sys.argv", ["tdk", "fail"])
    assert tdk.main() == 1
    out, err = capfd.readouterr()
    assert "tdk got: fail" in out and "tdk exited with status 1" in err


def test_refuses_when_the_program_is_missing_from_the_venv(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "managed-venvs"
    (root / "uv" / "v2").mkdir(parents=True)
    (root / "v2.json").write_text('{"manager": "uv"}\n')
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_VENV", "v2")
    monkeypatch.setattr("sys.argv", ["tdk"])
    assert tdk.main() == 1
    assert "not installed in managed venv v2" in capsys.readouterr().err
