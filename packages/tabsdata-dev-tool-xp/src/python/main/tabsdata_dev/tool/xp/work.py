#
# Copyright 2026 Tabsdata Inc.
#
"""A suite run's working directory, and the ``${xp:dir}`` / ``${xp:project}`` tokens.

Every run has one: ``<scratch>/work``, made on first use and left behind with the
rest of the scratch dir, so what a run collected there -- the operations a
``--emit-ops`` wrote, the files a check script downloaded -- is still there to
read after it. A one-shot's create-instance and run-suite share one scratch dir,
and so one work dir.

A suite value may name it: ``${xp:dir}`` in a domain's ``emit_ops``, a domain
call's options or an action's options and params, and ``${xp:project}`` (the
project the run is for) where a project is known. They are replaced when the value
is used, not when the suite is read: the work dir is a run's, and a suite is read
before any run. Any other ``${xp:...}`` left once the suite is resolved (see
``ids``) is refused when the suite is read.

``${td:profile}`` is the run's tdk connection, for the steps that call tdk
themselves (``tdd tdk ...``, a check script), written ``"--profile",
"${td:profile}"``: the name the run was given with ``--profile``, or the empty
string when it was given none. Any other ``${td:...}`` is refused when the
suite is read. A separate namespace from ``${xp:...}`` because it is tdk's
setting, not the run's.
"""

from __future__ import annotations

import pathlib
import re

from . import state
from .reporter import scratch

TOKEN_RE = re.compile(r"\$\{xp:([A-Za-z][A-Za-z0-9_-]*(?:\([^)]*\))?)\}")
WORK_DIR = "dir"
PROJECT = "project"
TOKENS = (WORK_DIR, PROJECT)

TD_TOKEN_RE = re.compile(r"\$\{td:([^}]*)\}")
TD_PROFILE = "${td:profile}"


def work_dir() -> pathlib.Path:
    """This run's working directory, made on first use."""
    dest = scratch() / "work"
    dest.mkdir(parents=True, exist_ok=True)
    return dest


def unknown(text: str) -> list[str]:
    """The ``${xp:...}`` names in `text` that are not tokens -- for the suite
    validators, so a typo fails when the suite is read."""
    return [m for m in TOKEN_RE.findall(text) if m not in TOKENS]


def td_misuse(text: str) -> str | None:
    """Why `text` may not hold the ``${td:...}`` it holds, or None."""
    for name in TD_TOKEN_RE.findall(text):
        if name != "profile":
            return f"${{td:{name}}} is not a token (known: {TD_PROFILE})"
    return None


def expand(text: str, project: str | None = None) -> str:
    """`text` with every ``${xp:...}`` token replaced, and ``${td:profile}``
    by the run's profile name or the empty string. ``${xp:project}`` where no
    project is known -- a phase verb that only reaches the domains -- is an
    error rather than a literal left for a command to trip over."""

    def one(m: re.Match) -> str:
        name = m.group(1)
        if name == WORK_DIR:
            return str(work_dir())
        if name == PROJECT and project:
            return project
        state.die(f"${{xp:{name}}} has no value here (in {text!r})")

    text = text.replace(TD_PROFILE, state.run.profile or "")
    return TOKEN_RE.sub(one, text)
