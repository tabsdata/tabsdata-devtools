#
# Copyright 2026 Tabsdata Inc.
#

"""`_xp-execute`: a script runs with `from tdd import tdd` working, on this venv
or on a one-off venv named by xp; `tdd()` is tdd-exe, its output and failure."""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys

import pytest

from tabsdata_dev.tool import xp_execute


def _fake_tdd_exe(bin_dir: pathlib.Path) -> None:
    """A tdd-exe that echoes its arguments, and fails on `boom`."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    exe = bin_dir / "tdd-exe"
    exe.write_text(
        "#!/bin/sh\n"
        'if [ "$1" = boom ]; then echo "it broke" >&2; exit 3; fi\n'
        'echo "args: $*"\n'
    )
    exe.chmod(0o755)


SCRIPT = (
    "import sys\n"
    "from tdd import tdd, TddError\n"
    "print(tdd('pqt', 'csv', 'f.parquet').strip())\n"
    "try:\n"
    "    tdd('boom')\n"
    "except TddError as exc:\n"
    "    print('failed', exc.status, exc.output.strip())\n"
    "print('python', sys.executable)\n"
    "sys.exit(int(sys.argv[1]))\n"
)


@pytest.fixture
def script(tmp_path, monkeypatch):
    _fake_tdd_exe(tmp_path / "bin")
    monkeypatch.setenv("PATH", f"{tmp_path / 'bin'}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.delenv(xp_execute.VENV_ENV, raising=False)
    s = tmp_path / "check.py"
    s.write_text(SCRIPT)
    return s


def test_a_script_runs_with_tdd_importable_and_its_status_comes_back(script, capfd):
    assert xp_execute.main([str(script), "0"]) == 0
    out = capfd.readouterr().out
    assert "args: pqt csv f.parquet" in out
    assert "failed 3 it broke" in out
    assert f"python {sys.executable}" in out
    assert xp_execute.main([str(script), "4"]) == 1  # a non-zero status fails the run


def test_a_one_off_venv_gets_the_tdd_module_and_runs_the_script(
    script, tmp_path, monkeypatch, capfd
):
    venv = tmp_path / "tdd-xp-execute-x"
    subprocess.run(
        [sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True
    )
    monkeypatch.setenv(xp_execute.VENV_ENV, str(venv))
    assert xp_execute.main([str(script), "0"]) == 0
    out = capfd.readouterr().out
    assert "args: pqt csv f.parquet" in out
    ran_on = out.split("python ", 1)[1].strip()
    assert pathlib.Path(ran_on).parent.parent == venv
    purelib = xp_execute.site_packages(xp_execute.venv_python(venv))
    assert (purelib / "tdd.py").read_text() == xp_execute.module_text()


def test_a_one_off_venv_that_is_not_one_is_an_error(
    script, tmp_path, monkeypatch, capfd
):
    monkeypatch.setenv(xp_execute.VENV_ENV, str(tmp_path / "nothing"))
    assert xp_execute.main([str(script), "0"]) == 1


def test_note_prints_one_marked_line_for_xp_to_read(tmp_path, capfd):
    s = tmp_path / "noted.py"
    s.write_text("from tdd import note\nnote('812 rows,\\n  3 rows/s')\n")
    assert xp_execute.main([str(s)]) == 0
    assert capfd.readouterr().out.splitlines() == ["xp-note: 812 rows, 3 rows/s"]


def test_the_tdd_module_is_standard_library_only():
    """It runs in whatever venv a script asked for, so it imports nothing else."""
    import ast

    tree = ast.parse(xp_execute.module_text())
    imported = {
        (node.module or "").split(".")[0]
        if isinstance(node, ast.ImportFrom)
        else alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, (ast.Import, ast.ImportFrom))
        for alias in node.names
    }
    assert imported <= {"__future__", "subprocess", "sys", "pathlib"}, imported
