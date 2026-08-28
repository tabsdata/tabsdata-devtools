#
# Copyright 2026 Tabsdata Inc.
#

"""The runner the `system`, `domain` and `domain-sf` tools call.

Applies docs/command-cli-guidelines.md around :func:`dispatch.dispatch`: reads
``--format`` / ``--verbose`` from raw argv (a verb's own parser sees them too),
binds one renderer, runs the verb under a detail log when it is a chatty one,
and maps the outcome onto exactly one ``ok`` or ``error`` event and exit 0/1.
``--latch FILE`` is honoured for the long-running verbs.
"""

from __future__ import annotations

import sys
import traceback
from pathlib import Path

from tabsdata_dev.common.core import latch as core_latch
from tabsdata_dev.common.core import render
from tabsdata_dev.common.systems import cli, console, constants, dispatch


def _common(argv: list[str]) -> tuple[str, bool, list[str]]:
    """``--format`` / ``--verbose`` wherever they sit, and argv without them --
    so `tdd domain --format json --help` is still a help request."""
    fmt, verbose, rest = "view", False, []
    skip = False
    for i, arg in enumerate(argv):
        if skip:
            skip = False
            continue
        if arg in ("-v", constants.OPT_VERBOSE):
            verbose = True
        elif (
            arg == constants.OPT_FORMAT
            and i + 1 < len(argv)
            and argv[i + 1] in ("json", "view")
        ):
            fmt = argv[i + 1]
            skip = True
        elif arg.startswith(f"{constants.OPT_FORMAT}=") and arg.split("=", 1)[1] in (
            "json",
            "view",
        ):
            fmt = arg.split("=", 1)[1]
        else:
            rest.append(arg)
    return fmt, verbose, rest


def _log_prefix(tool: str, verb: str, argv: list[str]) -> str:
    """``tdd-<tool>-<verb>-<name>-`` for the detail log's file name."""
    if dispatch._is_domain_tool(tool):
        name = cli.peek(argv, constants.OPT_DOMAIN) or cli.peek(argv, constants.OPT_SYS)
    else:
        name = cli.peek(argv, constants.OPT_SYS) or cli.peek(argv, constants.OPT_TYPE)
    return f"tdd-{tool}-{verb}-" + (f"{name}-" if name else "")


def run(tool: str, argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    fmt, verbose, words = _common(argv)
    if not words or words[0] in constants.HELP_FLAGS:
        out = render.Renderer(tool, fmt=fmt, verbose=verbose)
        text, fields = dispatch.top_help(tool)
        return out.ok(text, **fields)
    # The verb is the first word that is not a common option; its own parser
    # still sees everything after it (the common options are declared on it).
    verb = words[0]
    rest = argv[argv.index(verb) + 1 :]
    argv = [verb, *rest]
    out = render.Renderer(f"{tool}-{verb}", fmt=fmt, verbose=verbose)
    console.bind(out)
    wants_help = any(a in constants.HELP_FLAGS for a in rest)

    latch = None
    if verb in dispatch.LATCH_VERBS and not wants_help:
        raw = cli.peek(rest, constants.OPT_LATCH)
        if raw:
            latch = Path(raw)
            core_latch.clear(latch)
    logged = verb in dispatch.LOGGED_VERBS and not wants_help

    def finish(code: int) -> int:
        if latch is not None:
            core_latch.touch(latch, ok=(code == 0))
        return code

    try:
        if logged:
            console.prune_logs(
                constants.LOG_DIR, f"tdd-{tool}-", constants.LOG_MAX_AGE_DAYS
            )
            with console.activate(constants.LOG_DIR, _log_prefix(tool, verb, rest)):
                rc = dispatch.dispatch(tool, argv)
        else:
            rc = dispatch.dispatch(tool, argv)
    except SystemExit as exc:  # argparse --help
        return finish(0 if exc.code in (0, None) else 1)
    except KeyboardInterrupt:
        console.flush_good()
        out.error("interrupted", log=_log())
        return finish(1)
    except cli.UsageError as exc:
        console.flush_good()
        out.error(str(exc), log=_log())
        return finish(1)
    except render_errors() as exc:
        console.flush_good()
        out.error(str(exc), log=_log())
        return finish(1)
    except Exception as exc:  # noqa: BLE001 - one error line, the traceback in the log
        console.flush_good()
        out.error(
            f"{type(exc).__name__}: {exc}", details=traceback.format_exc(), log=_log()
        )
        return finish(1)
    if console.is_final():
        return finish(rc)
    if rc != 0:
        console.flush_good()
        out.error(
            f"{tool} {verb} failed (exit {rc})",
            log=_log(),
            **console.take_result(),
        )
        return finish(1)
    out.ok(console.last_good() or f"{tool} {verb}: done", **console.take_result())
    return finish(0)


def _log() -> str | None:
    path = console.log_path()
    return str(path) if path else None


def render_errors():
    from tabsdata_dev.common.core.errors import ToolError

    return ToolError
