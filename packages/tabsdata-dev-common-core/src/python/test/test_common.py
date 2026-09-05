#
# Copyright 2026 Tabsdata Inc.
#

import os
import pytest
import io
import json

from tabsdata_dev.common.core import cli, parallel, proc, render


def test_map_bounded_preserves_order():
    assert parallel.map_bounded(lambda n: n * 2, range(6)) == [0, 2, 4, 6, 8, 10]


def test_map_bounded_handles_empty():
    assert parallel.map_bounded(str, []) == []


def _renderer(fmt, verbose=False):
    out, err = io.StringIO(), io.StringIO()
    return render.Renderer("t", fmt=fmt, verbose=verbose, out=out, err=err), out, err


def test_json_lines_carry_command_event_message_and_fields():
    r, out, err = _renderer("json")
    assert r.ok("done", count=3) == 0
    line = json.loads(out.getvalue())
    assert line == {"command": "t", "event": "ok", "message": "done", "count": 3}
    assert err.getvalue() == ""


def test_view_sends_ok_to_stdout_and_the_rest_to_stderr():
    r, out, err = _renderer("view")
    r.info("working")
    r.warn("careful")
    r.ok("done")
    assert out.getvalue() == "done\n"
    assert err.getvalue() == "working\ncareful\n"


def test_debug_is_shown_only_when_verbose():
    quiet, out, _ = _renderer("json")
    quiet.debug("hidden")
    assert out.getvalue() == ""
    loud, out, _ = _renderer("json", verbose=True)
    loud.debug("shown")
    assert json.loads(out.getvalue())["event"] == "debug"


def test_no_colour_off_a_terminal():
    r, out, _ = _renderer("view")
    r.ok("plain")
    assert "\033[" not in out.getvalue()


def test_colour_codes_by_kind(monkeypatch):
    class Tty(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.delenv("NO_COLOR", raising=False)
    tty = Tty()
    assert render.colored("ok", "x", tty) == "\033[32mx\033[0m"
    assert render.colored("error", "x", tty) == "\033[31mx\033[0m"
    assert render.colored("warn", "x", tty) == "\033[33mx\033[0m"
    assert render.colored("debug", "x", tty) == "\033[37mx\033[0m"
    assert render.colored("info", "x", tty) == "x"
    monkeypatch.setenv("NO_COLOR", "1")
    assert render.colored("ok", "x", tty) == "x"


def test_error_writes_a_log_and_returns_1(tmp_path, monkeypatch):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    r, out, err = _renderer("json")
    assert r.error("broke", details="trace") == 1
    line = json.loads(out.getvalue())
    assert line["event"] == "error" and line["message"] == "broke"
    log = tmp_path / line["log"].split("/")[-1]
    assert log.name.startswith("tdd-t-") and "details:\ntrace" in log.read_text()


def test_run_maps_usage_errors_and_exceptions_to_exit_1(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert cli.run("t", "d", lambda a, o: o.ok("fine"), argv=[]) == 0
    assert (
        cli.run(
            "t", "d", lambda a, o: o.ok("fine"), argv=["--bogus", "--format", "json"]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out.splitlines()[-1])["event"] == "error"
    assert cli.run("t", "d", lambda a, o: 1 / 0, argv=["--format=json"]) == 1
    assert "ZeroDivisionError" in json.loads(capsys.readouterr().out)["message"]
    assert cli.run("t", "d", lambda a, o: o.ok("x"), argv=["--help"]) == 0


def test_run_allows_anything_outside_a_tdd_dispatch(monkeypatch):
    monkeypatch.delenv("_TDD_TOOL", raising=False)
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    assert proc.run(["true"]).returncode == 0


def test_run_refuses_an_undeclared_binary(monkeypatch, tmp_path):
    (tmp_path / "catalog.json").write_text(
        '{"tools": {"demo-exe1": {"toolset": "demo-env1", "reqs": ["git"]}}}'
    )
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_TOOL", "demo-exe1")
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    try:
        proc.run(["jq", "."])
    except proc.UndeclaredRequirement as exc:
        assert "bin-reqs.txt" in str(exc)
        return
    raise AssertionError("expected UndeclaredRequirement")


def test_run_maps_sys_exit_and_interrupt_to_the_model(tmp_path, monkeypatch, capsys):
    import sys

    monkeypatch.setattr(render, "LOG_DIR", tmp_path)
    assert cli.run("t", "d", lambda a, o: sys.exit(0), argv=[]) == 0
    assert cli.run("t", "d", lambda a, o: sys.exit("bad"), argv=["--format=json"]) == 1
    assert json.loads(capsys.readouterr().out)["message"] == "bad"

    def interrupted(a, o):
        raise KeyboardInterrupt

    assert cli.run("t", "d", interrupted, argv=["--format=json"]) == 1
    assert json.loads(capsys.readouterr().out)["message"] == "interrupted"


def test_read_field_goes_through_op_read(monkeypatch):
    import subprocess

    from tabsdata_dev.common.core import secrets

    calls = []

    def fake_run(argv, **kwargs):
        calls.append(argv)
        return subprocess.CompletedProcess(
            argv, 0, stdout="s3cr3t-value-123\n", stderr=""
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    assert (
        secrets.read_field("1p", "Employee", "DevSecrets", "TD_BACKENDS_CRYPTO_KEY")
        == "s3cr3t-value-123"
    )
    assert calls[-1] == [
        "op",
        "read",
        "op://Employee/DevSecrets/TD_BACKENDS_CRYPTO_KEY",
    ]


def test_read_field_reports_op_failures(monkeypatch, tmp_path):
    import subprocess

    from tabsdata_dev.common.core import secrets

    def fake_run(argv, **kw):
        if argv[0] == "which":  # the `op` presence probe passes
            return subprocess.CompletedProcess(
                argv, 0, stdout="/usr/bin/op\n", stderr=""
            )
        return subprocess.CompletedProcess(
            argv, 1, stdout="", stderr="[ERROR] not signed in"
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    try:
        secrets.read_field("1p", "Employee", "DevSecrets", "X")
    except secrets.ToolError as exc:
        assert "not signed in" in str(exc)
        return
    raise AssertionError("expected ToolError")


def test_managedvenv_needs_tdd_venv_and_points_at_tdd_venv(monkeypatch):
    from tabsdata_dev.common.core import managedvenv
    from tabsdata_dev.common.core.errors import ToolError

    monkeypatch.delenv("_TDD_VENV", raising=False)
    # and nothing for `adopted` to find either: the developer running this may
    # well have a managed venv of their own active
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ToolError, match="tdd venv"):
        managedvenv.active()
    monkeypatch.setenv("_TDD_VENV", "work")
    assert managedvenv.active() == "work"


def test_managedvenv_adopts_a_managed_venv_active_without_the_record(
    tmp_path, monkeypatch
):
    from tabsdata_dev.common.core import managedvenv
    from tabsdata_dev.common.core.errors import ToolError

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.delenv("_TDD_VENV", raising=False)
    for var in ("VIRTUAL_ENV", "CONDA_PREFIX", "CONDA_DEFAULT_ENV"):
        monkeypatch.delenv(var, raising=False)
    root = tmp_path / "managed-venvs"
    (root / "uv" / "w").mkdir(parents=True)
    (root / "w.env").write_text("uv\n")
    (root / "conda" / "c").mkdir(parents=True)
    (root / "c.env").write_text("conda\n")
    # a uv/pyenv venv: VIRTUAL_ENV is the path
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "w"))
    assert managedvenv.active() == "w"
    # the record wins over the environment
    monkeypatch.setenv("_TDD_VENV", "other")
    assert managedvenv.active() == "other"
    monkeypatch.delenv("_TDD_VENV")
    # not ours: outside the root, a deeper path, or a marker that disagrees
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "elsewhere" / "w"))
    with pytest.raises(ToolError, match="tdd venv"):
        managedvenv.active()
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "w" / "deeper"))
    assert managedvenv.adopted() is None
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "pyenv" / "w"))
    assert managedvenv.adopted() is None
    monkeypatch.delenv("VIRTUAL_ENV")
    # conda: the prefix, unless it is base
    monkeypatch.setenv("CONDA_PREFIX", str(root / "conda" / "c"))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", str(root / "conda" / "c"))
    assert managedvenv.active() == "c"
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    assert managedvenv.adopted() is None


def test_managedvenv_resolves_the_marker_and_composes_each_manager(
    tmp_path, monkeypatch
):
    from tabsdata_dev.common.core import managedvenv
    from tabsdata_dev.common.core.errors import ToolError

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    root = tmp_path / "managed-venvs"
    for manager in ("pyenv", "uv", "conda"):
        (root / manager / f"v-{manager}").mkdir(parents=True)
        (root / f"v-{manager}.env").write_text(f"{manager}\n")
    assert managedvenv.resolve("v-uv") == ("uv", root / "uv" / "v-uv")
    with pytest.raises(ToolError, match="does not exist"):
        managedvenv.resolve("nope")
    (root / "odd.env").write_text("virtualenvwrapper\n")
    with pytest.raises(ToolError, match="unknown venv manager"):
        managedvenv.resolve("odd")

    argv, env = managedvenv.launch("uv", root / "uv" / "v-uv", "tdk", ["fn", "--x"])
    assert argv == ["uv", "run", "--active", "--no-project", "tdk", "fn", "--x"]
    assert env == {"VIRTUAL_ENV": str(root / "uv" / "v-uv")}
    argv, env = managedvenv.launch("conda", root / "conda" / "v-conda", "tdk", [])
    assert argv[:3] == ["conda", "run", "--prefix"] and "--no-capture-output" in argv
    assert argv[-1] == "tdk" and env == {}
    argv, env = managedvenv.launch(
        "pyenv", root / "pyenv" / "v-pyenv", "tdkserver", ["a"]
    )
    assert argv == [str(root / "pyenv" / "v-pyenv" / "bin" / "tdkserver"), "a"]
    assert env["VIRTUAL_ENV"] == str(root / "pyenv" / "v-pyenv")
    assert env["PATH"].startswith(str(root / "pyenv" / "v-pyenv" / "bin") + os.pathsep)


def test_tool_argv_goes_through_the_tdd_dir_dispatcher(monkeypatch, tmp_path):
    from tabsdata_dev.common.core import proc

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    argv = proc.tool_argv("tdk", "status")
    assert argv == [
        str(tmp_path / "tdd-venvs" / "tdd" / "bin" / "tdd-exe"),
        "--dir",
        str(tmp_path),
        "tdk",
        "status",
    ]


def test_ports_stay_below_the_ephemeral_range_honour_exclude_and_skip_busy_ones(
    monkeypatch,
):
    import socket

    from tabsdata_dev.common.core import ports
    from tabsdata_dev.common.core.errors import ToolError

    lo, hi = ports.PORT_RANGE
    assert (
        lo >= 30000 and hi < 32768
    )  # above the systems' slots, below Linux's ephemeral floor
    found = ports.find_free_ports(12)
    assert len(set(found)) == 12 and all(lo <= p <= hi for p in found)
    # a range of one's own, walked from its start: stable, and exclude is honoured
    rng = (found[0], found[0] + 3)
    assert ports.find_free_port(rng, from_start=True) == found[0]
    assert (
        ports.find_free_port(rng, from_start=True, exclude={found[0]}) == found[0] + 1
    )
    with pytest.raises(ToolError, match="free port"):
        ports.find_free_ports(5, rng, from_start=True)
    # a port something listens on is skipped
    busy = socket.socket()
    busy.bind(("", found[0]))
    busy.listen(1)
    try:
        assert ports.find_free_port(rng, from_start=True) == found[0] + 1
        assert not ports.is_free(found[0]) and ports.is_free(found[0] + 1)
    finally:
        busy.close()


def test_config_derives_its_template_from_the_parser_and_writes_atomically(
    tmp_path, monkeypatch
):
    import argparse

    from tabsdata_dev.common.core import config

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument("--type", default="pyenv", help="the tool that creates it")
    parser.add_argument("--force", action="store_true", help="overwrite")
    parser.add_argument("--name", help="required, so no default to write")
    subs = parser.add_subparsers(dest="action")
    create = subs.add_parser("create")
    create.add_argument("--python", default="3.12", help="interpreter")

    doc = config.from_parser("demo", parser)
    assert doc.defaults() == {
        "": {"type": "pyenv", "force": False},  # --name has no default: left out
        "create": {"python": "3.12"},
    }
    text = config.render_doc(doc)
    # a template: every option commented at its default, so nothing is pinned
    assert '# type = "pyenv"' in text and "# force = false" in text
    assert "[options.create]" in text and '# python = "3.12"' in text
    assert "name" not in text.split("[options]")[1].split("[options.create]")[0]

    config.write("demo", text)
    assert config.path("demo") == tmp_path / "demo.toml"
    # every option is commented out, so the tables are there but empty
    assert config.options_in("demo") == {"": {}, "create": {}}
    # nothing of the temporary file survives a successful write
    assert [p.name for p in tmp_path.iterdir()] == ["demo.toml"]

    # uncommenting one line makes it a default, and --show says so
    config.path("demo").write_text(text.replace('# type = "pyenv"', 'type = "uv"'))
    assert config.options_in("demo") == {"": {"type": "uv"}, "create": {}}
    message, changed = config.show(doc, io.StringIO())
    assert changed == {"type": "uv"} and 'type = "uv"' in message
    assert '(default "pyenv")' in message


def test_config_rewrites_the_template_but_keeps_what_the_command_keeps(
    tmp_path, monkeypatch
):
    import argparse

    from tabsdata_dev.common.core import config

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument("--type", default="pyenv")
    doc = config.from_parser("demo", parser)
    config.write("demo", config.render_doc(doc) + '\n[repos."o/n"]\nlabels = ["bug"]\n')
    config.path("demo").write_text(
        config.path("demo").read_text().replace('# type = "pyenv"', 'type = "uv"')
    )

    config.update("demo", doc)  # what --create --force does
    text = config.path("demo").read_text()
    assert 'type = "uv"' in text  # what the file set
    assert '[repos."o/n"]' in text and 'labels = ["bug"]' in text  # what it keeps
    assert config.kept_tables("demo").startswith('[repos."o/n"]')


def test_the_argv_mapping_covers_flags_lists_and_values():
    from tabsdata_dev.common.core import config

    assert config.to_argv("dry_run", True) == ["--dry-run"]
    assert config.to_argv("dry_run", False) == []
    assert config.to_argv("suite", ["a", "b"]) == ["--suite", "a", "--suite", "b"]
    assert config.to_argv("type", "uv") == ["--type", "uv"]
