#
# Copyright 2026 Tabsdata Inc.
#

"""`_venv`: markers written, read, migrated, listed and removed -- the build
itself stood in for, since uv, pyenv and conda are the managers' business."""

from __future__ import annotations

import json
import os
import pathlib
import sys

import pytest

from tabsdata_dev.tool import venv as tool


@pytest.fixture
def tdd_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    (tmp_path / "VERSION").write_text("9.9.9\n")

    def fake_build(manager, prefix, python, relocatable):
        (prefix / "bin").mkdir(parents=True)
        os.symlink(sys.executable, prefix / "bin" / "python")
        if relocatable:
            (prefix / "pyvenv.cfg").write_text("relocatable = true\n")

    monkeypatch.setattr(tool, "_build", fake_build)
    monkeypatch.setattr(tool.shutil, "which", lambda m: f"/usr/bin/{m}")
    monkeypatch.setattr(tool, "manager_version", lambda m: "1.2.3")
    return tmp_path


def run(capsys, *argv) -> tuple[int, list[dict]]:
    capsys.readouterr()
    rc = tool.cli.run(
        tool.NAME,
        tool.DESCRIPTION,
        tool.body,
        argv=[*argv, "--format", "json"],
        configure=tool.configure,
    )
    events = [
        json.loads(ln)
        for ln in capsys.readouterr().out.splitlines()
        if ln.startswith("{")
    ]
    return rc, events


def test_create_writes_the_marker_of_what_the_venv_turned_out_to_be(tdd_dir, capsys):
    rc, events = run(capsys, "create", "--name", "w1", "--type", "uv", "--relocatable")
    assert rc == 0
    ok = events[-1]
    assert ok["name"] == "w1" and ok["type"] == "uv" and ok["relocatable"] is True
    assert (
        ok["python"] == sys.version.split()[0]
        and ok["python_requested"] == tool.DEFAULT_PYTHON
    )
    marker = json.loads((tdd_dir / "managed-venvs" / "w1.json").read_text())
    assert marker["manager"] == "uv" and marker["manager_version"] == "1.2.3"
    assert marker["tdd_version"] == "9.9.9" and marker["schema"] == 1
    assert pathlib.Path(ok["path"]) == tdd_dir / "managed-venvs" / "uv" / "w1"


@pytest.mark.parametrize(
    "argv, why",
    [
        (["--name", ".hidden"], "invalid name"),
        (["--name", "a b"], "invalid name"),
        (
            ["--name", "p", "--type", "pyenv", "--relocatable"],
            "--relocatable needs --type uv",
        ),
    ],
)
def test_create_refuses_what_cannot_be_made(tdd_dir, capsys, argv, why):
    rc, events = run(capsys, "create", *argv)
    assert rc == 1 and why in events[-1]["message"]


def test_create_again_needs_force_and_force_replaces_it_under_its_old_type(
    tdd_dir, capsys
):
    assert run(capsys, "create", "--name", "w", "--type", "uv")[0] == 0
    rc, events = run(capsys, "create", "--name", "w", "--type", "conda")
    assert (
        rc == 1
        and "already exists (type uv); --force recreates it" in events[-1]["message"]
    )
    rc, events = run(capsys, "create", "--name", "w", "--type", "conda", "--force")
    assert rc == 0 and events[-1]["recreated"] is True
    assert not (tdd_dir / "managed-venvs" / "uv" / "w").exists()
    assert (tdd_dir / "managed-venvs" / "conda" / "w").is_dir()


def test_list_marks_the_active_one_and_a_lost_directory(tdd_dir, capsys):
    run(capsys, "create", "--name", "a", "--type", "uv")
    run(capsys, "create", "--name", "b", "--type", "uv")
    import shutil

    shutil.rmtree(tdd_dir / "managed-venvs" / "uv" / "b")
    rc, events = run(capsys, "list", "--active", "a")
    ok = events[-1]
    assert rc == 0 and [v["name"] for v in ok["venvs"]] == ["a", "b"]
    assert ok["venvs"][0]["active"] and not ok["venvs"][1]["exists"]
    lines = ok["message"].splitlines()
    assert lines[0].endswith("(active)") and lines[1].endswith("(missing directory)")


def test_delete_refuses_the_active_venv_and_all_while_one_is(tdd_dir, capsys):
    run(capsys, "create", "--name", "a", "--type", "uv")
    run(capsys, "create", "--name", "b", "--type", "uv")
    rc, events = run(capsys, "delete", "--name", "a", "--active", "a")
    assert (
        rc == 1
        and "a is active; run tdd venv deactivate first" in events[-1]["message"]
    )
    rc, events = run(capsys, "delete", "--all", "--active", "a")
    assert rc == 1 and "is active" in events[-1]["message"]
    rc, events = run(capsys, "delete", "--name", "a", "--all")
    assert rc == 1 and "--all and --name are exclusive" in events[-1]["message"]
    rc, events = run(capsys, "delete", "--all")
    assert rc == 0 and [d["name"] for d in events[-1]["deleted"]] == ["a", "b"]
    assert not list((tdd_dir / "managed-venvs").glob("*.json"))


def test_info_describes_one_venv_and_names_an_unknown_one(tdd_dir, capsys):
    run(capsys, "create", "--name", "a", "--type", "uv")
    rc, events = run(capsys, "info", "--name", "a")
    assert rc == 0 and events[-1]["type"] == "uv" and events[-1]["exists"]
    rc, events = run(capsys, "info", "--name", "nope")
    assert rc == 1 and "no managed venv named nope" in events[-1]["message"]


def test_a_pre_json_marker_is_migrated_before_anything_else(tdd_dir, capsys):
    prefix = tdd_dir / "managed-venvs" / "uv" / "old"
    (prefix / "bin").mkdir(parents=True)
    os.symlink(sys.executable, prefix / "bin" / "python")
    # A real home: 3.13 trusts it to find the stdlib, and a python that cannot
    # start probes as no version at all.
    home = pathlib.Path(sys._base_executable).parent
    (prefix / "pyvenv.cfg").write_text(f"home = {home}\nrelocatable = true\n")
    (tdd_dir / "managed-venvs" / "old.env").write_text("uv\n")
    rc, events = run(capsys, "list")
    assert rc == 0 and [v["name"] for v in events[-1]["venvs"]] == ["old"]
    marker = json.loads((tdd_dir / "managed-venvs" / "old.json").read_text())
    assert marker["relocatable"] is True and "migrated" in marker
    assert marker["python"] == sys.version.split()[0]
    assert not (tdd_dir / "managed-venvs" / "old.env").exists()


def test_a_windows_venv_is_asked_through_scripts(tmp_path):
    """Layouts are asked of the venv, never of the platform: a venv built on
    Windows keeps its python in Scripts\\, a conda env at its root."""
    win = tmp_path / "win"
    (win / "Scripts").mkdir(parents=True)
    (win / "Scripts" / "python.exe").write_text("")
    assert tool.python_of(win) == win / "Scripts" / "python.exe"
    conda = tmp_path / "conda"
    conda.mkdir()
    (conda / "python.exe").write_text("")
    assert tool.python_of(conda) == conda / "python.exe"
    assert tool.python_of(tmp_path / "none") is None
