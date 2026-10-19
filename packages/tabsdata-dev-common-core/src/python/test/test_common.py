#
# Copyright 2026 Tabsdata Inc.
#

import os
import pytest
import io
import json
import sys

from tabsdata_dev.common.core import cli, parallel, proc, render
from tabsdata_dev.common.core.errors import ToolError


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
        '{"tools": {"demo-exe1": {"toolset": "demo-env1", "required": ["git"]}}}'
    )
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_TOOL", "demo-exe1")
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    for launch in (proc.run, proc.popen):
        with pytest.raises(proc.UndeclaredRequirement, match="bin-reqs.txt"):
            launch(["jq", "."])


@pytest.fixture
def dispatched(monkeypatch, tmp_path):
    """A tool `demo` run by tdd, declaring `git`, its toolset's bin/ empty."""
    catalog = {"tools": {"demo": {"toolset": "demo-env", "required": ["git"]}}}
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("_TDD_TOOL", "demo")
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    bin_dir = proc.venv_scripts(tmp_path / "tdd-venvs" / "demo-env")
    bin_dir.mkdir(parents=True)
    yield bin_dir
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()


def test_on_windows_a_program_is_known_by_its_name_without_suffix_in_any_case(
    dispatched,
    monkeypatch,
):
    """Windows runs `git` as git.exe and matches names in any case; a pinned
    `uv` sits in the toolset's Scripts\\ as uv.exe. Neither may read as an
    undeclared binary there -- and a suffix Windows does not execute is still
    a different name."""
    monkeypatch.setattr(proc, "WINDOWS", True)
    monkeypatch.setenv("PATHEXT", ".COM;.EXE;.BAT;.CMD")
    (dispatched / "uv.exe").write_text("")
    for argv0 in (
        "git",
        "git.exe",
        "GIT.EXE",
        r"C:\Program Files\Git\git.exe",
        "uv",
    ):
        proc._check([argv0])
    for argv0 in ("git.sh", "jq", "jq.exe"):
        with pytest.raises(proc.UndeclaredRequirement):
            proc._check([argv0])


def test_a_tool_may_run_its_family_s_binaries_and_its_optional_ones(
    dispatched,
    monkeypatch,
    tmp_path,
):
    """Under PowerShell smoke may run pwsh, not bash; an optional binary is
    declared, so allowed -- whether it is installed is checked where used."""
    catalog = {
        "tools": {
            "demo": {
                "toolset": "demo-env",
                "required": {"unix": ["bash"], "powershell": ["pwsh"]},
                "optional": ["conda"],
            }
        }
    }
    (tmp_path / "catalog.json").write_text(json.dumps(catalog))
    monkeypatch.setattr(proc, "WINDOWS", False)
    monkeypatch.setenv("_TDD_SHELL_FAMILY", "powershell")
    proc._declared.cache_clear()
    proc._check(["pwsh"])
    proc._check(["conda"])
    with pytest.raises(proc.UndeclaredRequirement):
        proc._check(["bash"])


def test_elsewhere_a_program_name_is_exact(dispatched, monkeypatch):
    monkeypatch.setattr(proc, "WINDOWS", False)
    (dispatched / "uv").write_text("")
    proc._check(["git"])
    proc._check(["uv"])
    for argv0 in ("git.exe", "GIT", "uv.exe"):
        with pytest.raises(proc.UndeclaredRequirement):
            proc._check([argv0])


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


def _no_venv(monkeypatch):
    # the developer running this may well have a venv of their own active
    for var in (
        "_TDD_VENV",
        "_TDD_VENV_ACTIVATED",
        "VIRTUAL_ENV",
        "CONDA_PREFIX",
        "CONDA_DEFAULT_ENV",
    ):
        monkeypatch.delenv(var, raising=False)


def test_on_windows_only_uv_venvs_are_supported(monkeypatch, tmp_path):
    from tabsdata_dev.common.core import managedvenv

    monkeypatch.setattr(managedvenv, "WINDOWS", True)
    monkeypatch.setattr(managedvenv.shutil, "which", lambda name: f"/x/{name}")
    managedvenv.require_manager("uv")
    for manager in ("pyenv", "conda"):
        with pytest.raises(ToolError, match="not supported on Windows"):
            managedvenv.require_manager(manager)
        # and a launcher refuses one already made, as creating one is refused
        with pytest.raises(ToolError, match="not supported on Windows"):
            managedvenv.launch(manager, tmp_path / "v", "tdk", [])


def test_a_venv_manager_is_checked_only_where_it_is_used(monkeypatch, tmp_path):
    """pyenv and conda are optional: a conda venv fails plainly without conda,
    and a pyenv venv never needs pyenv -- its program runs by path."""
    from tabsdata_dev.common.core import managedvenv

    monkeypatch.setattr(managedvenv, "WINDOWS", False)
    monkeypatch.setattr(managedvenv.shutil, "which", lambda name: None)
    with pytest.raises(ToolError, match="this is a conda venv, and conda is not"):
        managedvenv.launch("conda", tmp_path / "v", "tdk", [])
    argv, _env = managedvenv.launch("pyenv", tmp_path / "v", "tdk", ["status"])
    assert argv[-1] == "status" and "pyenv" not in argv


def test_a_windows_export_gives_powershell_every_value_exactly(
    tmp_path,
    resource_folder,
):
    """The file an operator carries to Windows and dot-sources: each value
    comes back as it was -- quotes, typographic quotes, $ and backticks that
    must not expand, a PEM over several lines, non-ASCII text."""
    import shutil
    import subprocess

    from tabsdata_dev.common.core import secrets

    pwsh = shutil.which("pwsh")
    if pwsh is None:
        pytest.skip("pwsh not installed")
    # macOS and Linux share the sh form; anything else is refused
    assert secrets.render({"A": "x y"}, "export", "linux") == "export A='x y'"
    assert secrets.render({"A": "x y"}, "export") == "export A='x y'"
    with pytest.raises(ToolError, match="unknown platform"):
        secrets.render({"A": "x"}, "export", "solaris")
    values = {
        "TD_PLAIN": "s3cret",
        "TD_QUOTES": 'it\'s "q" \u2018curly\u2019 \u201alow\u201b',
        "TD_EXPAND": "$HOME `n $(whoami) ${x}",
        "TD_PEM": "-----BEGIN KEY-----\nAAAA\nBBBB\n-----END KEY-----",
        "TD_UNICODE": "ña \u00e7a \u65e5\u672c",
        "TD_EMPTY": "",
    }
    text = secrets.render(values, "export", "windows")
    assert text.startswith("# Secrets exported by `tdd _1p fetch --platform windows`")
    file = tmp_path / "secrets.ps1"
    file.write_text(text, encoding="utf-8")
    done = subprocess.run(
        [pwsh, "-NoProfile", "-File", resource_folder / "load_ps1.ps1", file, *values],
        capture_output=True,
        encoding="utf-8",
    )
    assert done.returncode == 0, done.stderr
    seen = json.loads(done.stdout)
    # an empty value: PowerShell on Windows removes the variable, elsewhere it
    # keeps it empty -- the platform's rule, not the file's
    assert seen.pop("TD_EMPTY") in ("", None)
    assert seen == {k: v for k, v in values.items() if k != "TD_EMPTY"}


def test_managedvenv_needs_a_venv_and_says_how_to_get_one(tmp_path, monkeypatch):
    from tabsdata_dev.common.core import managedvenv
    from tabsdata_dev.common.core.errors import ToolError

    _no_venv(monkeypatch)
    with pytest.raises(ToolError, match="tdd venv.*_TDD_VENV=NAME"):
        managedvenv.select()
    assert managedvenv.select(required=False) is None
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    (tmp_path / "managed-venvs" / "uv" / "work").mkdir(parents=True)
    (tmp_path / "managed-venvs" / "work.json").write_text('{"manager": "uv"}')
    monkeypatch.setenv("_TDD_VENV", "work")
    assert managedvenv.select().name == "work"


def test_managedvenv_the_venv_last_activated_wins(tmp_path, monkeypatch):
    """`tdd venv activate` really activates, so the shell's venv is the latest
    -- unless _TDD_VENV was set by hand, which _TDD_VENV_ACTIVATED (what tdd
    venv exported) tells apart from tdd's own record."""
    from tabsdata_dev.common.core import managedvenv

    _no_venv(monkeypatch)
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    root = tmp_path / "managed-venvs"
    for name in ("w", "m"):
        (root / "uv" / name).mkdir(parents=True)
        (root / f"{name}.json").write_text('{"manager": "uv"}')
    mine = tmp_path / "project" / ".venv"
    (mine / "bin").mkdir(parents=True)

    def pick():
        v = managedvenv.select()
        return v.name or v.path, v.why

    # tdd venv activate w: the record and the shell agree
    monkeypatch.setenv("_TDD_VENV", "w")
    monkeypatch.setenv("_TDD_VENV_ACTIVATED", "w")
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "w"))
    assert pick() == ("w", "the venv active in the shell")
    # then a project venv entered on top by hand: it is the last one
    monkeypatch.setenv("VIRTUAL_ENV", str(mine))
    v = managedvenv.select()
    assert (v.path, v.name, v.manager) == (mine, None, "venv")
    assert "not managed by tdd" in v.describe()
    # then _TDD_VENV=m by hand (inline or exported): later still
    monkeypatch.setenv("_TDD_VENV", "m")
    assert pick() == ("m", "_TDD_VENV=m, set by hand")
    # a shell from before _TDD_VENV_ACTIVATED: its _TDD_VENV wins, as it did
    monkeypatch.setenv("_TDD_VENV", "w")
    monkeypatch.delenv("_TDD_VENV_ACTIVATED")
    assert pick()[0] == "w"
    # the record alone, the shell's venv left by hand: the record is all there is
    monkeypatch.setenv("_TDD_VENV_ACTIVATED", "w")
    monkeypatch.delenv("VIRTUAL_ENV")
    assert pick()[0] == "w" and "record" in pick()[1]
    # a smoke run from a shell in a project venv: the script's own `tdd venv
    # create` activates its venv in the script's shell, and that one is used
    # by every tdd tdk the script runs, however deep
    monkeypatch.setenv("VIRTUAL_ENV", str(mine))
    monkeypatch.delenv("_TDD_VENV")
    monkeypatch.delenv("_TDD_VENV_ACTIVATED")
    assert managedvenv.select().path == mine
    monkeypatch.setenv("_TDD_VENV", "m")
    monkeypatch.setenv("_TDD_VENV_ACTIVATED", "m")
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "m"))
    assert pick() == ("m", "the venv active in the shell")
    # a conda env tdd does not manage; conda's base is not a venv
    monkeypatch.delenv("VIRTUAL_ENV")
    monkeypatch.delenv("_TDD_VENV")
    env = tmp_path / "miniforge" / "envs" / "td"
    (env / "conda-meta").mkdir(parents=True)
    monkeypatch.setenv("CONDA_PREFIX", str(env))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "td")
    assert managedvenv.select().manager == "conda"
    monkeypatch.setenv("CONDA_DEFAULT_ENV", "base")
    assert managedvenv.select(required=False) is None


def test_managedvenv_reads_a_windows_layout_off_the_venv(tmp_path, monkeypatch):
    """Scripts\\ and .exe are asked of the venv, not of the platform -- what a
    venv built on Windows has, whichever OS the test runs on."""
    from tabsdata_dev.common.core import managedvenv

    win = tmp_path / "win"
    (win / "Scripts").mkdir(parents=True)
    (win / "Scripts" / "tdk.exe").write_text("")
    assert managedvenv.bin_dir(win) == win / "Scripts"
    assert managedvenv.program(win, "tdk") == win / "Scripts" / "tdk.exe"
    assert managedvenv.program(win, "km") is None
    assert managedvenv.path_dirs(win, "uv") == [win / "Scripts"]
    assert managedvenv.path_dirs(win, "conda") == [
        win,
        win / "Scripts",
        win / "Library" / "bin",
    ]
    argv, env = managedvenv.launch("pyenv", win, "tdk", ["x"])
    assert argv == [str(win / "Scripts" / "tdk.exe"), "x"]
    assert env["PATH"].split(os.pathsep)[0] == str(win / "Scripts")
    argv, env = managedvenv.launch("conda", win, "tdk", [])
    assert argv[-1] == str(win / "Scripts" / "tdk.exe")
    assert env["PATH"].split(os.pathsep)[:3] == [
        str(win),
        str(win / "Scripts"),
        str(win / "Library" / "bin"),
    ]
    mine = managedvenv.Venv(win, "venv", None, "the venv active in the shell")
    argv, env = managedvenv.launch_in(mine, "tdk", ["a"])
    assert argv == [str(win / "Scripts" / "tdk.exe"), "a"]
    assert env["VIRTUAL_ENV"] == str(win)
    assert env["PATH"].split(os.pathsep)[0] == str(win / "Scripts")


def test_managedvenv_adopts_a_managed_venv_active_without_the_record(
    tmp_path, monkeypatch
):
    from tabsdata_dev.common.core import managedvenv

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    _no_venv(monkeypatch)
    root = tmp_path / "managed-venvs"
    (root / "uv" / "w").mkdir(parents=True)
    (root / "w.json").write_text('{"manager": "uv", "python": "3.12.13"}\n')
    (root / "conda" / "c").mkdir(parents=True)
    (root / "c.json").write_text('{"manager": "conda"}\n')
    # a uv/pyenv venv: VIRTUAL_ENV is the path
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "w"))
    assert managedvenv.adopted() == "w"
    # not ours: outside the root, a deeper path, or a marker that disagrees
    monkeypatch.setenv("VIRTUAL_ENV", str(tmp_path / "elsewhere" / "w"))
    assert managedvenv.adopted() is None
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "uv" / "w" / "deeper"))
    assert managedvenv.adopted() is None
    monkeypatch.setenv("VIRTUAL_ENV", str(root / "pyenv" / "w"))
    assert managedvenv.adopted() is None
    monkeypatch.delenv("VIRTUAL_ENV")
    # conda: the prefix, unless it is base
    monkeypatch.setenv("CONDA_PREFIX", str(root / "conda" / "c"))
    monkeypatch.setenv("CONDA_DEFAULT_ENV", str(root / "conda" / "c"))
    assert managedvenv.adopted() == "c"
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
        (root / f"v-{manager}.json").write_text(
            '{"schema": 1, "manager": "%s", "python": "3.12.13", '
            '"relocatable": false}\n' % manager
        )
    assert managedvenv.resolve("v-uv") == ("uv", root / "uv" / "v-uv")
    assert managedvenv.marker("v-uv") == {
        "schema": 1,
        "manager": "uv",
        "python": "3.12.13",
        "relocatable": False,
    }
    with pytest.raises(ToolError, match="does not exist"):
        managedvenv.resolve("nope")
    (root / "odd.json").write_text('{"manager": "virtualenvwrapper"}\n')
    with pytest.raises(ToolError, match="unknown venv manager"):
        managedvenv.resolve("odd")
    # not a marker at all: not JSON, or JSON that names no manager
    (root / "junk.json").write_text("uv\n")
    with pytest.raises(ToolError, match="not a managed venv marker"):
        managedvenv.resolve("junk")
    (root / "bare.json").write_text('{"python": "3.12.13"}\n')
    with pytest.raises(ToolError, match="not a managed venv marker"):
        managedvenv.resolve("bare")
    # the marker from before the JSON: `tdd venv` migrates it, this side says so
    (root / "old.env").write_text("uv\n")
    with pytest.raises(ToolError, match="older tdd.*tdd venv list"):
        managedvenv.resolve("old")

    argv, env = managedvenv.launch("uv", root / "uv" / "v-uv", "tdk", ["fn", "--x"])
    assert argv == ["uv", "run", "--active", "--no-project", "tdk", "fn", "--x"]
    assert env == {"VIRTUAL_ENV": str(root / "uv" / "v-uv")}
    argv, env = managedvenv.launch("conda", root / "conda" / "v-conda", "tdk", [])
    assert argv[:3] == ["conda", "run", "--prefix"] and "--no-capture-output" in argv
    # by path, never by name: in a shell with that env already active a bare
    # name resolved to the launcher itself, which recursed forever
    assert argv[-1] == str(root / "conda" / "v-conda" / "bin" / "tdk")
    assert env["PATH"].startswith(str(root / "conda" / "v-conda" / "bin") + os.pathsep)
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
    # every option the command takes, the ones with no built-in default read as
    # empty -- those are most of what is worth configuring (a directory, a
    # prefix), and the shell half has always shown them that way
    assert doc.defaults() == {
        "": {"type": "pyenv", "force": False, "name": ""},
        "create": {"python": "3.12"},
    }
    # ... and an empty one is not passed on, so a line copied out of `--show`
    # leaves the option alone rather than handing it an empty argument
    assert config.to_argv("name", "") == []
    assert config.to_argv("name", "x") == ["--name", "x"]
    text = config.render_doc(doc)
    # the tables and nothing else: no option is written down, so the reader's
    # file never holds a stale copy of today's defaults
    assert "[options]" in text and "[options.create]" in text
    assert "pyenv" not in text and "force" not in text and "3.12" not in text
    # the one thing it explains, and the copyright: no other commentary
    assert "[options.<SUBCOMMAND>]" in text and "double quotes" in text
    assert len([ln for ln in text.splitlines() if ln.startswith("#")]) == 5

    config.write("demo", text)
    assert config.path("demo") == tmp_path / "demo.toml"
    # empty tables: the file sets nothing until the reader writes a line
    assert config.options_in("demo") == {"": {}, "create": {}}
    # nothing of the temporary file survives a successful write
    assert [p.name for p in tmp_path.iterdir()] == ["demo.toml"]

    # writing a line makes it a default, and --show says so
    config.path("demo").write_text(text.replace("[options]", '[options]\ntype = "uv"'))
    assert config.options_in("demo") == {"": {"type": "uv"}, "create": {}}
    message, changed = config.show(doc, io.StringIO())
    assert changed == {"type": "uv"} and 'type = "uv"' in message
    assert 'type = "uv"   (built in default: "pyenv")' in message


def test_show_prints_the_tables_a_command_has_beyond_the_options(tmp_path, monkeypatch):
    """`--show` answers "what is in effect", which includes the tables a command
    has besides options -- naming them was not an answer.

    Two rules the wording of that answer depends on. Every table is its own
    subject, so setting one in the file cannot hide what another defaults to.
    And a default SUB-table is a shape to copy, `[repo."OWNER/NAME"]`, named for
    nothing that exists: it belongs in the template and never in `--show`.
    """
    import argparse
    import io

    from tabsdata_dev.common.core import config

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument("--type", default="pyenv")
    tables = '# [demo]\n# vault = "dev_ci"\n#\n# [repo."OWNER/NAME"]\n# labels = []\n'
    doc = config.from_parser("demo", parser, tables=tables)

    message, _ = config.show(doc, io.StringIO())
    assert "beyond the options:" in message
    assert "[demo]" in message and 'vault = "dev_ci"' in message
    assert "OWNER/NAME" not in message  # the placeholder is not state

    # a file that sets one table leaves the others at their defaults, and a real
    # sub-table is shown where the placeholder never was
    config.write("demo", config.render_doc(doc) + '\n[repo."o/n"]\nlabels = ["bug"]\n')
    message, _ = config.show(doc, io.StringIO())
    assert 'vault = "dev_ci"' in message  # [demo] untouched by the file
    assert '[repo."o/n"]' in message and 'labels = ["bug"]' in message
    assert "OWNER/NAME" not in message

    # and a key the file sets wins, key by key
    config.write("demo", config.render_doc(doc) + '\n[demo]\nvault = "mine"\n')
    message, _ = config.show(doc, io.StringIO())
    assert 'vault = "mine"' in message


def test_show_paints_a_built_in_green_and_what_the_file_sets_blue(
    tmp_path, monkeypatch
):
    """The rendering both halves owe, to the escape: a value at its built-in
    default is green, a value this file sets is blue with that built-in named
    in white beside it, and every line carries its own paint -- headers
    included, so the message reads the same whether or not the file sets
    anything. `common.sh:_tdd_config_show` prints exactly these lines; a
    difference between the two is a bug.
    """
    import argparse
    import io

    from tabsdata_dev.common.core import config, render

    class TTY(io.StringIO):
        def isatty(self):
            return True

    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.delenv("NO_COLOR", raising=False)
    parser = argparse.ArgumentParser(prog="demo")
    parser.add_argument("--type", default="pyenv")
    parser.add_argument("--greeting", default="hello")
    doc = config.from_parser("demo", parser, tables='# [demo]\n# vault = "dev_ci"\n')
    config.write(
        "demo",
        config.render_doc(doc, {"": {"greeting": "hello again"}})
        + "\n[demo]\nkeep = true\n",
    )

    green = f"\033[{render.PAINTS['green']}m"
    blue = f"\033[{render.PAINTS['blue']}m"
    white = f"\033[{render.PAINTS['white']}m"
    off = render.RESET

    painted, changed = config.show(doc, TTY())
    assert changed == {"greeting": "hello again"}
    assert (
        f'  {blue}greeting = "hello again"{off}'
        f'   {white}(built in default: "hello"){off}'
    ) in painted
    assert f'  {green}type = "pyenv"{off}' in painted
    assert f"{green}[options]{off}" in painted
    assert f"{green}beyond the options:{off}" in painted
    # the same two paints beyond the options, and no built-in quoted there:
    # the value shown IS the default, so there is no second one to name
    beyond = painted.split("beyond the options:")[1]
    assert f'  {green}vault = "dev_ci"{off}' in beyond
    assert f"  {blue}keep = true{off}" in beyond
    assert "built in default" not in beyond

    # a pipe and NO_COLOR get the same lines with no escape at all
    plain, _ = config.show(doc, io.StringIO())
    assert "\033" not in plain
    assert 'greeting = "hello again"   (built in default: "hello")' in plain
    monkeypatch.setenv("NO_COLOR", "1")
    assert config.show(doc, TTY())[0] == plain


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
        config.path("demo").read_text().replace("[options]", '[options]\ntype = "uv"')
    )

    config.update("demo", doc)  # what --create --force does
    text = config.path("demo").read_text()
    assert 'type = "uv"' in text  # what the file set
    assert '[repos."o/n"]' in text and 'labels = ["bug"]' in text  # what it keeps
    assert config.kept_tables("demo").startswith('[repos."o/n"]')


def test_a_vault_sweep_skips_the_items_titled_for_the_reader(monkeypatch):
    """A shared vault is also where people keep notes to themselves, and every
    field of it lands in the caller's shell as a variable. An item titled `_...`
    says it is not config, and is skipped before it is even read -- one `op item
    get` per item, so a vault of scratch notes would pay for each of them.

    The title is checked as 1Password shows it, before normalisation: `_norm`
    maps a leading `-` to `_` as well, and checking after would hide items
    nobody meant to hide.
    """
    import json as json_mod
    import subprocess

    from tabsdata_dev.common.core import secrets_1p
    from tabsdata_dev.common.core.errors import ToolError

    vault = [
        {"title": "S3"},
        {"title": "_scratch"},
        {"title": "-dashes"},
        {"title": "GCPPOSTGRES"},
    ]
    read: list[str] = []

    class _Done:
        def __init__(self, out):
            self.returncode = 0
            self.stdout = out
            self.stderr = ""

    def fake_run(argv, **kwargs):
        if argv[0] == "which":
            return _Done("")
        if "list" in argv:
            return _Done(json_mod.dumps(vault))
        title = argv[argv.index("get") + 1]
        read.append(title)
        return _Done(
            json_mod.dumps(
                {
                    "title": title,
                    "fields": [
                        {"id": "bucket", "value": f"{title}-b"},
                        {"id": "expires", "value": "2099-12-31"},
                        {"id": "empty", "value": None},
                    ],
                }
            )
        )

    monkeypatch.setattr(subprocess, "run", fake_run)
    found = secrets_1p.fetch("dev_xp")

    assert sorted(read) == ["-dashes", "GCPPOSTGRES", "S3"]  # `_scratch` never read
    assert set(found) == {"S3__BUCKET", "GCPPOSTGRES__BUCKET", "_DASHES__BUCKET"}
    assert found["S3__BUCKET"] == "S3-b"
    # an expires field is bookkeeping and a null one has nothing to export
    assert not [k for k in found if k.endswith(("EXPIRES", "EMPTY"))]

    # a vault of nothing but those says so, rather than handing back an empty
    # environment somebody then has to explain to themselves
    vault[:] = [{"title": "_one"}, {"title": "_two"}]
    with pytest.raises(ToolError, match="nothing to load"):
        secrets_1p.fetch("dev_xp")


def test_the_argv_mapping_covers_flags_lists_and_values():
    from tabsdata_dev.common.core import config

    assert config.to_argv("dry_run", True) == ["--dry-run"]
    assert config.to_argv("dry_run", False) == []
    assert config.to_argv("suite", ["a", "b"]) == ["--suite", "a", "--suite", "b"]
    assert config.to_argv("type", "uv") == ["--type", "uv"]


def test_help_is_coloured_by_structure_and_only_for_a_terminal():
    from tabsdata_dev.common.core import render

    text = (
        "usage: tdd demo [-h]\n"
        "\n"
        "A paragraph that is prose and must stay plain, even at length.\n"
        "\n"
        "options:\n"
        "  -v, --verbose         show debug events too\n"
        "                        a wrapped description line\n"
        "\n"
        "example:\n"
        "  tdd demo --verbose\n"
    )

    class TTY(io.StringIO):
        def isatty(self):
            return True

    plain = render.colorize_help(text, io.StringIO())  # not a terminal
    assert plain == text
    painted = render.colorize_help(text, TTY())
    assert f"\033[{render.HELP_HEADING}moptions:\033[0m" in painted
    assert f"  \033[{render.HELP_TERM}m-v, --verbose\033[0m" in painted
    assert "usage:\033[0m tdd demo" in painted
    # prose, wrapped descriptions and an example's command are left alone
    assert "A paragraph that is prose and must stay plain, even at length." in painted
    assert "                        a wrapped description line" in painted
    assert "  tdd demo --verbose\n" in painted
    # a line something else already painted is never painted twice
    already = "  \033[32m--format\033[0m  json or view\n"
    assert render.colorize_help(already, TTY()) == already


def test_generated_password_carries_every_class_and_nothing_that_bites():
    """A generated password has to survive three journeys unchanged, and a rule
    at the end of one of them: Cloud SQL rejects a password with no
    non-alphanumeric character (INVALID_PASSWORD), while a quoted SQL literal, a
    DB-API driver's `%` placeholders and an un-encoded URL each rule characters
    out. The safe symbols are the URL-unreserved ones."""
    from tabsdata_dev.common.core.passwords import SAFE_SYMBOLS, gen_password

    passwords = [gen_password() for _ in range(200)]
    assert {len(p) for p in passwords} == {24}
    assert len(set(passwords)) == len(passwords)  # not a fixed string
    for p in passwords:
        assert any(c.isupper() for c in p), p
        assert any(c.islower() for c in p), p
        assert any(c.isdigit() for c in p), p
        assert any(not c.isalnum() for c in p), p  # Cloud SQL requires one
        # a quote or backslash would end the SQL literal it sits in, `%` is a
        # placeholder to psycopg2, and the rest are URL-reserved
        assert not set(p) & set("%'\"\\@:/?#&"), p
        assert set(p) - set(SAFE_SYMBOLS) <= set(
            "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789"
        ), p
    assert gen_password(8)  # a short one still returns something usable


def test_a_tool_error_carries_diagnostics_into_the_log_and_not_the_terminal(capsys):
    """The terminal keeps one line of what went wrong; the log gets what the
    failing system said. A raise site that pulled the database's DETAIL or a
    container's last log lines puts them on the error, and the runner writes them
    under the message -- without widening the one line a person reads."""
    from tabsdata_dev.common.core.errors import ToolError

    def body(args, out):
        raise ToolError(
            "permission denied for schema public", "DETAIL: it is owned by x"
        )

    assert cli.run("probe", "d", body, argv=[]) == 1
    shown = capsys.readouterr().err
    # the diagnostics are NOT on the terminal, only the pointer to the log
    assert "permission denied for schema public" in shown
    assert "DETAIL: it is owned by x" not in shown
    path = shown.split("details: ", 1)[1].strip().splitlines()[0]
    written = open(path).read()
    assert "error:   permission denied for schema public" in written
    assert "DETAIL: it is owned by x" in written
    os.unlink(path)


def test_a_plain_tool_error_still_writes_a_log_without_a_details_block(capsys):
    """Nothing has to change at a raise site that has nothing extra to say."""
    from tabsdata_dev.common.core.errors import ToolError

    assert ToolError("just the message").details == ""

    def body(args, out):
        raise ToolError("just the message")

    assert cli.run("probe", "d", body, argv=[]) == 1
    path = capsys.readouterr().err.split("details: ", 1)[1].strip().splitlines()[0]
    written = open(path).read()
    assert "just the message" in written and "\ndetails:" not in written
    os.unlink(path)


def test_container_failure_explains_itself_when_there_is_no_container():
    """It runs while something is already going wrong, so it never raises: an
    unusable container has to come back as text, not as a second exception."""
    from tabsdata_dev.common.core.docker import container_failure

    text = container_failure("tdd-no-such-container-probe")
    assert isinstance(text, str) and text


def test_confirm_takes_yes_from_the_flag_or_the_keyboard_and_nowhere_else(monkeypatch):
    """The guidelines reserve --yes for this, and silence is never a yes: with
    no terminal to ask on there is nobody to have agreed."""
    out = render.Renderer("probe")
    cli.confirm(out, "go ahead?", assume_yes=True)  # the flag is an answer

    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    monkeypatch.setattr(sys.stdin, "readline", lambda: "y\n", raising=False)
    cli.confirm(out, "go ahead?", assume_yes=False)
    monkeypatch.setattr(sys.stdin, "readline", lambda: "\n", raising=False)
    with pytest.raises(ToolError, match="aborted"):
        cli.confirm(out, "go ahead?", assume_yes=False)

    # no terminal, and json even on one: a machine reading JSON Lines is not
    # there to answer, and the prompt would be the one line that is not an event
    monkeypatch.setattr(sys.stdin, "isatty", lambda: False, raising=False)
    with pytest.raises(ToolError, match="no terminal to ask on"):
        cli.confirm(out, "go ahead?", assume_yes=False)
    monkeypatch.setattr(sys.stdin, "isatty", lambda: True, raising=False)
    with pytest.raises(ToolError, match="no terminal to ask on"):
        cli.confirm(render.Renderer("probe", fmt="json"), "go?", assume_yes=False)


class _Tty(io.StringIO):
    def isatty(self) -> bool:
        return True


def test_live_block_redraws_in_place_below_the_events(monkeypatch):
    """On a terminal the status block is erased and redrawn around every
    event, cut to the terminal's width, and the outcome removes it."""
    import os

    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setattr(
        render.shutil, "get_terminal_size", lambda *_: os.terminal_size((21, 24))
    )
    out, err = _Tty(), _Tty()
    r = render.Renderer("demo", out=out, err=err)
    assert r.can_live()
    r.live(["a: 10%", "b: a line far too long for it"])
    assert err.getvalue() == "a: 10%\nb: a line far too l…\n"
    r.info("step")
    assert err.getvalue().endswith("\033[2F\033[Jstep\na: 10%\nb: a line far too l…\n")
    r.live(["a: 20%"])
    assert err.getvalue().endswith("\033[2F\033[Ja: 20%\n")
    r.ok("done")
    assert err.getvalue().endswith("\033[1F\033[J") and out.getvalue() == "done\n"
    r.info("after")
    assert err.getvalue().endswith("\033[1F\033[Jafter\n")  # no block to redraw


def test_live_writes_nothing_off_a_terminal():
    import io

    for fmt, err in (("view", io.StringIO()), ("json", _Tty())):
        out = io.StringIO()
        r = render.Renderer("demo", fmt=fmt, out=out, err=err)
        assert not r.can_live()
        r.live(["a: 10%"])
        r.live([])
        assert err.getvalue() == "" and out.getvalue() == ""


def test_a_command_can_render_formats_of_its_own(capsys):
    """`formats` add --format values the body shapes itself; the renderer is
    view for them, so the outcome still reaches stdout, and one of them can be
    the default."""
    seen = []

    def body(args, out):
        seen.append((args.format, out.fmt))
        return out.ok("lines" if args.format == "export" else "summary")

    run = dict(formats={"export": "lines to eval"}, default_format="export")
    assert cli.run("demo", "d", body, argv=[], **run) == 0
    assert cli.run("demo", "d", body, argv=["--format", "json"], **run) == 0
    assert seen == [("export", "view"), ("json", "json")]
    out = capsys.readouterr().out
    assert out.startswith("lines\n") and '"message":"summary"' in out
    assert cli.run("demo", "d", body, argv=["--format", "xml"], **run) == 1
    assert cli.run("demo", "d", body, argv=["--format", "export"]) == 1  # not offered


@pytest.mark.skipif(os.name == "nt", reason="a job object is real there")
def test_a_job_holds_nothing_off_windows_so_callers_signal_the_group():
    """Off Windows a process group ends a tree, so a Job answers False and the
    caller takes its POSIX path; closing it twice is harmless."""
    from tabsdata_dev.common.core import proc

    job = proc.Job(os.getpid())
    assert job.terminate() is False
    job.close()
    job.close()
