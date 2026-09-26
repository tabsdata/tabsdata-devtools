#
# Copyright 2026 Tabsdata Inc.
#

"""mexe end to end against real directories and a real POSIX shell, plus the
pieces that decide which shell and which environment a command gets."""

import json
import os
import pathlib
import sys

import pytest

from tabsdata_dev.common.core import cli
from tabsdata_dev.tool import mexe

posix = pytest.mark.skipif(os.name == "nt", reason="drives sh")


@pytest.fixture
def dirs(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("SHELL", "/bin/sh")
    monkeypatch.delenv(mexe.FAMILY_ENV, raising=False)
    monkeypatch.delenv("_TDD_VENV", raising=False)
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.setenv("TDD_DIR", str(tmp_path / "no-tdd"))
    for name in ("a", "b", "c"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "name.txt").write_text(name + "\n")
    return tmp_path


def run(capsys, *argv):
    code = cli.run(
        mexe.NAME,
        mexe.DESCRIPTION,
        mexe.body,
        argv=["--format", "json", *argv],
        configure=mexe.configure,
    )
    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    return code, events


def lines(events, label=None):
    return [
        e["message"]
        for e in events
        if e["event"] == "info" and "line" in e and (label is None or e["dir"] == label)
    ]


def test_dirs_are_checked_before_anything_runs(dirs):
    with pytest.raises(mexe.ToolError, match="not a directory: nope"):
        mexe.parse_dirs("a,nope")
    with pytest.raises(mexe.ToolError, match="at least one"):
        mexe.parse_dirs(" , ")
    assert [t.name for t in mexe.parse_dirs("a, b/,a")] == ["a", "b"]


@posix
def test_pipes_run_in_each_dir_prefixed(dirs, capsys):
    code, events = run(capsys, "--dirs", "a,b", "cat name.txt | tr a-z A-Z")
    assert code == 0
    assert sorted(lines(events)) == ["[a] A", "[b] B"]
    assert events[-1]["event"] == "ok"
    assert [d["status"] for d in events[-1]["dirs"]] == ["ok", "ok"]


@posix
def test_several_words_are_one_command_its_options_included(dirs, capsys):
    # --execution after the command is the command's, not mexe's; the word
    # with a space reaches the program as one argument.
    code, events = run(
        capsys, "--dirs", "a", "printf", "%s|", "two words", "--execution", "serial"
    )
    assert code == 0
    assert lines(events) == ["[a] two words|--execution|serial|"]
    assert events[-1]["command_line"] == "printf '%s|' 'two words' --execution serial"


@posix
def test_a_double_dash_ends_mexes_options(dirs, capsys):
    code, events = run(capsys, "--dirs", "a", "--", "echo", "--dirs")
    assert code == 0
    assert lines(events) == ["[a] --dirs"]


@posix
def test_presets_tdd_appended_after_the_command_are_mexes(dirs, capsys, monkeypatch):
    tdd = dirs / "tdd"
    tdd.mkdir()
    (tdd / "mexe.toml").write_text(
        '[options]\ndirs = "a,b"\noutput = "on-completion"\n'
    )
    monkeypatch.setenv("TDD_DIR", str(tdd))
    # What tdd hands over for `tdd mexe cat name.txt` with that file.
    code, events = run(
        capsys, "cat", "name.txt", "--dirs", "a,b", "--output", "on-completion"
    )
    assert code == 0
    assert sorted(lines(events)) == ["[a] a", "[b] b"]
    assert events[-1]["command_line"] == "cat name.txt"


def test_one_argument_is_a_shell_line_several_are_quoted_words(monkeypatch):
    monkeypatch.delenv(mexe.FAMILY_ENV, raising=False)
    assert mexe.command_line(["ls | wc -l"]) == "ls | wc -l"
    assert mexe.command_line(["git", "commit", "-m", "a b"]) == "git commit -m 'a b'"
    monkeypatch.setenv(mexe.FAMILY_ENV, "powershell")
    assert mexe.command_line(["git", "log", "--format=%h it's"]) == (
        "git log '--format=%h it''s'"
    )
    assert mexe.command_line(["my tool", "a,b"]) == "& 'my tool' 'a,b'"


def test_only_the_trailing_presets_are_peeled():
    tables = {"": {"execution": "serial", "output": "on-completion", "verbose": True}}
    words, found = mexe.split_presets(
        ["git", "log", "--execution", "serial", "--verbose"], tables
    )
    assert words == ["git", "log"]
    assert found == {"execution": "serial", "verbose": True}
    assert mexe.split_presets(["git", "status"], tables) == (["git", "status"], {})


@posix
def test_continue_lets_the_others_finish(dirs, capsys):
    code, events = run(
        capsys,
        "--dirs",
        "a,b,c",
        "--execution",
        "serial",
        'test "$(cat name.txt)" != b',
    )
    assert code == 1
    assert [d["status"] for d in events[-1]["dirs"]] == ["ok", "fail", "ok"]
    assert "failed: b" in events[-1]["message"]


@posix
def test_abort_starts_no_more(dirs, capsys):
    code, events = run(
        capsys,
        "--dirs",
        "a,b,c",
        "--execution",
        "serial",
        "--on-error",
        "abort",
        'test "$(cat name.txt)" != a',
    )
    assert code == 1
    assert [d["status"] for d in events[-1]["dirs"]] == ["fail", "skipped", "skipped"]


@posix
def test_abort_stops_what_is_running_pipeline_included(dirs, capsys):
    # b fails at once; a is a pipeline that would outlive a killed shell and
    # hold the pipe open if only the shell were stopped.
    code, events = run(
        capsys,
        "--dirs",
        "a,b",
        "--on-error",
        "abort",
        'if [ "$(cat name.txt)" = a ]; then sleep 30 | cat; else exit 3; fi',
    )
    assert code == 1
    status = {d["dir"]: d["status"] for d in events[-1]["dirs"]}
    assert status == {"a": "aborted", "b": "fail"}


@posix
def test_on_completion_keeps_a_dirs_lines_together(dirs, capsys):
    code, events = run(
        capsys,
        "--dirs",
        "a,b",
        "--output",
        "on-completion",
        "for i in 1 2 3; do echo $i; sleep 0.05; done",
    )
    assert code == 0
    got = lines(events)
    assert got in (
        ["[a] 1", "[a] 2", "[a] 3", "[b] 1", "[b] 2", "[b] 3"],
        ["[b] 1", "[b] 2", "[b] 3", "[a] 1", "[a] 2", "[a] 3"],
    )


@posix
def test_stderr_is_part_of_the_output(dirs, capsys):
    code, events = run(capsys, "--dirs", "a", "echo out; echo err >&2")
    assert code == 0
    assert lines(events) == ["[a] out", "[a] err"]


def test_the_shell_is_the_family_not_the_os(monkeypatch):
    monkeypatch.setenv(mexe.FAMILY_ENV, "powershell")
    monkeypatch.setattr(mexe.shutil, "which", lambda name, path=None: f"/x/{name}")
    argv = mexe.shell_argv("Get-ChildItem | Measure-Object", [])
    assert argv[0] == "/x/pwsh" and argv[-2:] == [
        "-Command",
        mexe.PWSH_UTF8 + "Get-ChildItem | Measure-Object",
    ]
    assert "-NoProfile" in argv
    monkeypatch.delenv(mexe.FAMILY_ENV)
    # No family exported: pwsh on Windows, where there is no POSIX shell to
    # assume, the POSIX shell everywhere else.
    monkeypatch.setattr(mexe.os, "name", "nt")
    assert mexe.shell_argv("dir", [])[0] == "/x/pwsh"
    monkeypatch.setattr(mexe.os, "name", "posix")
    monkeypatch.setenv("SHELL", "/bin/zsh")
    assert mexe.shell_argv("ls | wc -l", []) == ["/bin/zsh", "-c", "ls | wc -l"]
    monkeypatch.delenv("SHELL")
    assert mexe.shell_argv("ls", []) == ["/x/sh", "-c", "ls"]


def test_tdds_own_bin_leaves_path_and_the_managed_venv_goes_first(
    tmp_path, monkeypatch
):
    own = str(pathlib.Path(sys.executable).parent)
    monkeypatch.setenv("PATH", os.pathsep.join([own, "/usr/bin", "/bin"]))
    monkeypatch.setenv("_TDD_TOOL", "mexe")
    monkeypatch.delenv("VIRTUAL_ENV", raising=False)
    monkeypatch.delenv("CONDA_PREFIX", raising=False)
    monkeypatch.delenv("_TDD_VENV", raising=False)
    monkeypatch.setenv("TDD_DIR", str(tmp_path))

    env, venv = mexe.child_env()
    assert venv is None
    assert env["PATH"].split(os.pathsep) == ["/usr/bin", "/bin"]
    assert "_TDD_TOOL" not in env

    where = tmp_path / "managed-venvs" / "uv" / "dev"
    (where / ("Scripts" if os.name == "nt" else "bin")).mkdir(parents=True)
    (tmp_path / "managed-venvs" / "dev.json").write_text('{"manager": "uv"}')
    monkeypatch.setenv("_TDD_VENV", "dev")
    env, venv = mexe.child_env()
    assert venv == "dev"
    assert env["VIRTUAL_ENV"] == str(where)
    assert env["PATH"].split(os.pathsep)[0] == str(mexe.venv_dirs("uv", where)[0])
    assert own not in env["PATH"].split(os.pathsep)


def test_a_named_venv_that_is_gone_is_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_VENV", "ghost")
    with pytest.raises(mexe.ToolError, match="ghost"):
        mexe.child_env()


@posix
def test_in_view_the_output_is_on_stdout_and_the_rest_on_stderr(dirs, capsys):
    code = cli.run(
        mexe.NAME,
        mexe.DESCRIPTION,
        mexe.body,
        argv=["--dirs", "a", "--output", "on-completion", "cat name.txt; echo e >&2"],
        configure=mexe.configure,
    )
    got = capsys.readouterr()
    assert code == 0
    assert got.out.splitlines() == [
        "[a] a",
        "[a] e",
        "1 dir(s): every command succeeded",
    ]
    assert "[a]" not in got.err
    assert "1 dir(s), one at a time" in got.err
