#
# Copyright 2026 Tabsdata Inc.
#
"""What one xp-run process knows about the run it is in.

The original tdx-xp kept these as module globals; they are gathered here so
every module reads the same renderer, dry-run flag, secret-env name, lane
bookkeeping and open reporter. ``bind()`` is called once, first thing in the
body, from the parsed arguments.
"""

from __future__ import annotations

import dataclasses
import pathlib
from typing import Any

from tabsdata_dev.common.core import render
from tabsdata_dev.common.core.errors import ToolError

TOOL = "xp-run"
DEFAULT_SECRET_ENV = "TD_BACKENDS_CRYPTO_KEY"
# A fan-out child inherits the parent's scratch root through this variable and
# takes a subdir of it named after its lane, so one group run leaves one tree.
SCRATCH_ENV = "TDD_XP_SCRATCH"


class XpError(ToolError):
    """An expected, user-facing failure: one error event, exit 1, no traceback."""


@dataclasses.dataclass
class Run:
    out: render.Renderer
    dry_run: bool = False
    fail_fast: bool = False
    secret_env: str = DEFAULT_SECRET_ENV
    # Multi-phase group run: lane token -> the phase it died in. None = no
    # multi-phase run is active (a lone fan-out is fatal on its own).
    lanes: dict[str, str] | None = None
    scratch: pathlib.Path | None = None
    reporter: Any = None  # reporter.Reporter | None
    summary: dict | None = None  # the closed reporter's report, for the final event


run = Run(out=render.Renderer(TOOL))


def bind(out: render.Renderer, args) -> None:
    global run
    run = Run(
        out=out,
        dry_run=bool(getattr(args, "dry_run", False)),
        fail_fast=bool(getattr(args, "fail_fast", False)),
        secret_env=getattr(args, "secret_env", None) or DEFAULT_SECRET_ENV,
    )


def die(msg: str):
    """Abort the run. Also to ``<scratch>/errors.log`` when a command is running
    -- a fan-out child's stderr is not the console, and this text is the one thing
    a failed run is read for. Only when a reporter is already open: the
    pointer-only verbs have no scratch dir and must not make one just to record
    that a suite path was wrong."""
    if run.reporter is not None:
        run.reporter.error("error", msg)
    raise XpError(msg)
