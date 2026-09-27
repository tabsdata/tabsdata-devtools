#
# Copyright 2026 Tabsdata Inc.
#
"""A suite run's working directory, and the ``${XP_*}`` tokens a suite names it by.

Every run has one: ``<scratch>/work``, made on first use and left behind with the
rest of the scratch dir, so what a run collected there -- the operations a
``--emit-ops`` wrote, the files a check script downloaded -- is still there to
read after it. A one-shot's create-instance and run-suite share one scratch dir,
and so one work dir.

A suite value may name it: ``${XP_WORK_DIR}`` in a domain's ``emit_ops``, a live
domain entry's options or an execute entry's params, and ``${XP_PROJECT}`` (the
project the run is for) where a project is known. They are replaced when the value
is used, not when the suite is read: the work dir is a run's, and a suite is read
before any run. An unknown ``${XP_*}`` name is refused when the suite is read.
"""

from __future__ import annotations

import pathlib
import re

from . import state
from .reporter import scratch

TOKEN_RE = re.compile(r"\$\{(XP_[A-Za-z0-9_]*)\}")
WORK_DIR = "XP_WORK_DIR"
PROJECT = "XP_PROJECT"
TOKENS = (WORK_DIR, PROJECT)


def work_dir() -> pathlib.Path:
    """This run's working directory, made on first use."""
    dest = scratch() / "work"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def unknown(text: str) -> list[str]:
    """The ``${XP_*}`` names in `text` that are not tokens -- for the suite
    validators, so a typo fails when the suite is read."""
    return [m for m in TOKEN_RE.findall(text) if m not in TOKENS]


def expand(text: str, project: str | None = None) -> str:
    """`text` with every ``${XP_*}`` token replaced. ``${XP_PROJECT}`` where no
    project is known -- a phase verb that only reaches the domains -- is an
    error rather than a literal left for a command to trip over."""

    def one(m: re.Match) -> str:
        name = m.group(1)
        if name == WORK_DIR:
            return str(work_dir())
        if name == PROJECT and project:
            return project
        state.die(f"${{{name}}} has no value here (in {text!r})")

    return TOKEN_RE.sub(one, text)
