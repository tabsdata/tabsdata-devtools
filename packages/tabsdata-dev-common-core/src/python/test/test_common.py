#
# Copyright 2026 Tabsdata Inc.
#

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
    monkeypatch.delenv("TDD_TOOL", raising=False)
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    assert proc.run(["true"]).returncode == 0


def test_run_refuses_an_undeclared_binary(monkeypatch, tmp_path):
    (tmp_path / "catalog.json").write_text(
        '{"tools": {"demo-exe1": {"toolset": "demo-env1", "reqs": ["git"]}}}'
    )
    monkeypatch.setenv("TDD_DIR", str(tmp_path))
    monkeypatch.setenv("TDD_TOOL", "demo-exe1")
    proc._declared.cache_clear()
    proc._toolset_bin.cache_clear()
    try:
        proc.run(["jq", "."])
    except proc.UndeclaredRequirement as exc:
        assert "bin-reqs.txt" in str(exc)
        return
    raise AssertionError("expected UndeclaredRequirement")
