#
# Copyright 2026 Tabsdata Inc.
#

import json

from tabsdata_dev.tdd import __main__ as main_mod
from tabsdata_dev.tdd import render
import os
import pytest


def _events(capsys):
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


def test_version_is_an_ok_event(capsys):
    assert main_mod.main(["--format", "json", "--version"]) == 0
    (event,) = _events(capsys)
    assert event["command"] == "tdd" and event["event"] == "ok"
    assert event["message"] == f"tdd {event['version']}"


def test_bad_format_is_an_error_with_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert main_mod.main(["--format", "xml", "--version"]) == 1
    assert "--format must be json or view" in capsys.readouterr().err


def test_uninitialized_dir_is_an_error_event(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert (
        main_mod.main(["--dir", str(tmp_path / "nope"), "--format=json", "info"]) == 1
    )
    (event,) = _events(capsys)
    assert event["event"] == "error" and "not initialized" in event["message"]
    assert event["log"].startswith(str(tmp_path))


def test_builtins_take_format_after_the_word(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert (
        main_mod.main(["--dir", str(tmp_path / "nope"), "doctor", "--format", "json"])
        == 1
    )
    assert _events(capsys)[0]["command"] == "doctor"


def test_builtins_reject_other_arguments(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert main_mod.main(["--format=json", "info", "--bogus"]) == 1
    assert "takes no argument" in _events(capsys)[0]["message"]


def test_reqs_reports_every_declaration(capsys):
    code = main_mod.main(["--format", "json", "--reqs"])
    events = _events(capsys)
    assert events[-1]["event"] in ("ok", "error")
    assert (code == 0) == (events[-1]["event"] == "ok")
    assert any(e["event"] == "info" and e.get("binary") == "jq" for e in events)


def test_tdd_install_help_and_usage_errors():
    from tabsdata_dev.tdd import install

    assert install.main(["--help"]) == 0


def test_tdd_install_usage_error_is_an_event(tmp_path, monkeypatch, capsys):
    from tabsdata_dev.tdd import install

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert install.main(["--bogus", "--format", "json"]) == 1
    (event,) = _events(capsys)
    assert event["command"] == "tdd-install" and event["event"] == "error"
    assert install.main(["--format", "xml"]) == 1


def test_generate_entry_point_reports_as_events(tmp_path, monkeypatch, capsys):
    from tabsdata_dev.tdd import generate

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert generate.main(["--bogus"]) == 1
    assert generate.main(["--help"]) == 0


def test_dispatch_refuses_when_a_declared_binary_is_missing(
    tmp_path, monkeypatch, capsys
):
    # The shell side always refused a command whose bin-reqs were missing; the
    # dispatcher must do the same for a Python tool, before exec, naming them.
    from tabsdata_dev.tdd import catalog as catalog_mod
    from tabsdata_dev.tdd import dispatch as dispatch_mod

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    exe = tmp_path / "tdd-venvs" / "t" / "bin" / "demo"
    exe.parent.mkdir(parents=True)
    exe.write_text("#!/bin/sh\n")
    exe.chmod(0o755)
    entry = {"toolset": "t", "package": "p", "reqs": ["surely-not-a-binary-xyz", "sh"]}
    monkeypatch.setattr(catalog_mod, "installed", lambda d: {"tools": {"demo": entry}})
    monkeypatch.setattr(catalog_mod, "is_stale", lambda d: False)
    monkeypatch.setattr(
        os, "execve", lambda *a, **k: pytest.fail("execve must not be reached")
    )
    out = render.Renderer("tdd", fmt="json")
    assert dispatch_mod.dispatch(tmp_path, "demo", [], out) == 1
    event = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    assert event["event"] == "error" and event["missing"] == ["surely-not-a-binary-xyz"]
    assert "tdd --reqs demo" in event["message"]


def test_a_shim_counts_only_when_its_manager_wires_it(tmp_path, monkeypatch):
    import subprocess

    from tabsdata_dev.tdd import reqs

    shims = tmp_path / "shims"
    shims.mkdir()
    shim = shims / "foo"
    shim.write_text(
        '#!/usr/bin/env bash\nprogram="${0##*/}"\nexec "/x/pyenv" exec "$program" "$@"\n'
    )
    shim.chmod(0o755)
    pyenv = shims / "pyenv"  # the manager itself must be findable to be asked
    pyenv.write_text("#!/bin/sh\n")
    pyenv.chmod(0o755)
    monkeypatch.setenv("PATH", str(shims))
    assert (
        reqs.shim_manager(str(shim)) == "pyenv"
        and reqs.shim_manager(str(pyenv)) is None
    )

    def unwired(argv, **kw):
        assert argv == ["pyenv", "which", "foo"]
        return subprocess.CompletedProcess(
            argv, 127, "", "pyenv: foo: command not found\n"
        )

    monkeypatch.setattr(subprocess, "run", unwired)
    path, note = reqs.resolve("foo")
    assert path is None and "not wired" in note and "command not found" in note
    assert reqs.missing(["foo"]) == [f"foo ({note})"]
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, "/real/bin/foo\n", ""),
    )
    assert (
        reqs.resolve("foo") == ("/real/bin/foo", "pyenv shim")
        and reqs.missing(["foo"]) == []
    )
    # the manager answering with the shim itself is not wiring either
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda argv, **kw: subprocess.CompletedProcess(argv, 0, f"{shim}\n", ""),
    )
    path, note = reqs.resolve("foo")
    assert path is None and "resolves to a shim" in note
    # a launcher script that execs the manager (Homebrew's pyenv) is NOT a shim
    launcher = shims / "brewpyenv"
    launcher.write_text('#!/bin/bash\nexec "/opt/x/libexec/pyenv" "$@"\n')
    assert reqs.shim_manager(str(launcher)) is None
    # a plain binary needs no manager
    assert reqs.resolve("pyenv") == (str(pyenv), "")
