#
# Copyright 2026 Tabsdata Inc.
#

"""Completion latches for long-running commands run in the background.

``--latch FILE``: the command writes ``FILE.ok`` or ``FILE.err`` and then
touches ``FILE``, so a waiter polls one path and reads the outcome from the
other two. Cleared at start so a stale latch from a previous run cannot be
mistaken for this one's.
"""

from __future__ import annotations

import pathlib
import sys


def files(latch: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    return pathlib.Path(f"{latch}.ok"), pathlib.Path(f"{latch}.err")


def clear(latch: pathlib.Path) -> None:
    ok, err = files(latch)
    for p in (latch, ok, err):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def touch(latch: pathlib.Path, *, ok: bool) -> None:
    ok_file, err_file = files(latch)
    try:
        latch.parent.mkdir(parents=True, exist_ok=True)
        (ok_file if ok else err_file).touch()
        latch.touch()
    except OSError as exc:
        print(f"warning: could not write latch {latch}: {exc}", file=sys.stderr)
