#
# Copyright 2026 Tabsdata Inc.
#

import shutil

from tabsdata_dev.tool import tdkserver


def test_requires_a_venv_activated_with_tdd_venv(monkeypatch, capsys):
    monkeypatch.delenv("_TDD_VENV", raising=False)
    # and nothing for `adopted` to find either: the developer running this may
    # well have a managed venv of their own active
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr("sys.argv", ["tdkserver", "--help"])
    assert tdkserver.main() == 1
    err = capsys.readouterr().err
    assert "_TDD_VENV" in err and "tdd venv" in err


def test_every_argument_reaches_the_program(
    tmp_path,
    monkeypatch,
    capfd,
    resource_folder,
):
    root = tmp_path / "managed-venvs"
    exe = root / "pyenv" / "v1" / "bin" / "tdkserver"
    exe.parent.mkdir(parents=True)
    (root / "v1.json").write_text('{"manager": "pyenv"}\n')
    shutil.copy(resource_folder / "echo_args.sh", exe)
    exe.chmod(0o755)
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_VENV", "v1")
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    # --help, --format, --version, -- : none of them is the launcher's
    monkeypatch.setattr(
        "sys.argv", ["tdkserver", "--help", "--format", "json", "--version", "--", "-v"]
    )
    assert tdkserver.main() == 0
    assert (
        "tdkserver got: --help --format json --version -- -v" in capfd.readouterr().out
    )
    monkeypatch.setattr("sys.argv", ["tdkserver", "fail"])
    assert tdkserver.main() == 1
    out, err = capfd.readouterr()
    assert "tdkserver got: fail" in out and "tdkserver exited with status 1" in err


def test_refuses_when_the_program_is_missing_from_the_venv(
    tmp_path, monkeypatch, capsys
):
    root = tmp_path / "managed-venvs"
    (root / "uv" / "v2").mkdir(parents=True)
    (root / "v2.json").write_text('{"manager": "uv"}\n')
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_VENV", "v2")
    monkeypatch.setattr("sys.argv", ["tdkserver"])
    assert tdkserver.main() == 1
    assert "not installed in managed venv v2" in capsys.readouterr().err


def test_runs_in_the_shells_venv_and_says_which(
    tmp_path,
    monkeypatch,
    capfd,
    resource_folder,
):
    """Any venv active in the shell will do, managed by tdd venv or not -- and
    the launcher names the one it picked, and why, before the program runs."""
    mine = tmp_path / "project" / ".venv"
    exe = mine / "bin" / "tdkserver"
    exe.parent.mkdir(parents=True)
    shutil.copy(resource_folder / "reports_venv.sh", exe)
    exe.chmod(0o755)
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    for var in ("_TDD_VENV", "_TDD_VENV_ACTIVATED", "CONDA_PREFIX", "_TDD_TOOL"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", str(mine))
    monkeypatch.setattr("sys.argv", ["tdkserver", "status"])
    assert tdkserver.main() == 0
    out, err = capfd.readouterr()
    assert f"tdkserver in {mine}" in out
    assert f"tdkserver: venv {mine} (venv, not managed by tdd)" in err
    assert "the venv active in the shell" in err


def test_refuses_one_of_tdds_own_toolset_venvs(tmp_path, monkeypatch, capsys):
    """Activated by hand, a toolset venv's tdkserver is this launcher: it would
    run itself forever."""
    own = tmp_path / "tdd" / "tdd-venvs" / "launchers"
    (own / "bin").mkdir(parents=True)
    (own / "bin" / "tdkserver").write_text("")
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "tdd"))
    for var in ("_TDD_VENV", "_TDD_VENV_ACTIVATED", "CONDA_PREFIX"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("VIRTUAL_ENV", str(own))
    monkeypatch.setattr("sys.argv", ["tdkserver"])
    assert tdkserver.main() == 1
    assert "one of tdd's own toolset venvs" in capsys.readouterr().err
