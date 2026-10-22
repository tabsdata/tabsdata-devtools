#
# Copyright 2026 Tabsdata Inc.
#

"""Where the commands' output goes: the renderer, plus a detail log.

The backends were written against ``console.out/good/bad/warn`` and plain
``print``; this module keeps that surface and routes it onto the event model
(docs/command-cli-guidelines.md): ``out`` and ``good`` are ``info`` events,
``bad`` and ``warn`` are ``warn`` events, and ``result(payload)`` records the
fields the run's final ``ok`` event carries (what ``--out json`` used to print).

The mutating verbs are chatty -- docker pulls, readiness waits, SQL DDL -- and
much of it is written by subprocesses straight to fd 1 and 2, where in json mode
it would corrupt the event stream. So those verbs run under :func:`activate`,
which redirects fd 1 & 2 into a timestamped detail log while the renderer keeps
writing to the real terminal. The same file becomes the failure log when the
verb fails, so there is one place to look either way.
"""

from __future__ import annotations

import contextlib
import os
import sys
import time
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from tabsdata_dev.common.core import render

_OUT: render.Renderer | None = None
_RESULT: dict | None = None
_LAST_GOOD: str | None = None
_FINAL = False
_LOG: Path | None = None


def bind(renderer: render.Renderer) -> None:
    """Route everything through `renderer` for this invocation."""
    global _OUT, _RESULT, _LAST_GOOD, _FINAL, _LOG
    _OUT, _RESULT, _LAST_GOOD, _FINAL, _LOG = renderer, None, None, False, None


def renderer() -> render.Renderer:
    global _OUT
    if _OUT is None:  # a unit test calling a verb function directly
        _OUT = render.Renderer("systems")
    return _OUT


def json_mode() -> bool:
    return renderer().fmt == "json"


def out(text: str = "") -> None:
    renderer().info(text)


def good(text: str) -> None:
    """A success line. The last one becomes the run's ``ok`` message, so it is
    held back rather than emitted -- printing it now and again as the ``ok``
    would show it twice. An earlier one is released as ``info`` when the next
    arrives (see :func:`flush_good` for a run that ends in an error)."""
    global _LAST_GOOD
    if _LAST_GOOD is not None:
        renderer().info(_LAST_GOOD, level="good")
    _LAST_GOOD = text


def flush_good() -> None:
    """Release a held-back good line as info -- for a run that then failed, so
    the line is not lost with the ok that never comes."""
    global _LAST_GOOD
    if _LAST_GOOD is not None:
        renderer().info(_LAST_GOOD, level="good")
        _LAST_GOOD = None


def bad(text: str) -> None:
    renderer().warn(text)


def warn(text: str) -> None:
    renderer().warn(text)


def debug(text: str) -> None:
    renderer().debug(text)


def result(payload: dict) -> None:
    """The machine-readable outcome (``{entity: {insert, update, delete}}``, a
    listing, ...): becomes the fields of the run's ``ok`` event."""
    global _RESULT
    _RESULT = payload


def take_result() -> dict:
    return dict(_RESULT or {})


def last_good() -> str | None:
    return _LAST_GOOD


def mark_final() -> None:
    """Something (the batch runner) already emitted the run's ok/error."""
    global _FINAL
    _FINAL = True


def is_final() -> bool:
    return _FINAL


def log_path() -> Path | None:
    return _LOG


# ---------------------------------------------------------------- detail log


def prune_logs(log_dir: str | Path, prefix: str, max_age_days: float) -> None:
    """Delete ``<prefix>*.log`` under `log_dir` older than `max_age_days` --
    best-effort, and only files carrying our own prefix."""
    d = Path(log_dir)
    if not d.is_dir():
        return
    cutoff = time.time() - max_age_days * 86400
    for p in d.glob(f"{prefix}*.log"):
        try:
            if p.stat().st_mtime < cutoff:
                p.unlink()
        except OSError:  # racing run, permissions -- skip
            pass


def _unique_log_path(log_dir: Path, name_prefix: str) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = log_dir / f"{name_prefix}{stamp}-{os.getpid()}.log"
    n = 1
    while path.exists():
        path = log_dir / f"{name_prefix}{stamp}-{os.getpid()}-{n}.log"
        n += 1
    return path


@contextmanager
def activate(log_dir: str | Path, name_prefix: str):
    """Send fd 1 & 2 (every ``print`` and every subprocess line) into a new
    detail log for the block, while the renderer keeps the real terminal."""
    global _LOG
    rend = renderer()
    log_dir = Path(log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    path = _unique_log_path(log_dir, name_prefix)

    sys.stdout.flush()
    sys.stderr.flush()
    term_fd = os.dup(1)
    err_fd = os.dup(2)
    term = os.fdopen(term_fd, "w", buffering=1, closefd=False, encoding="utf-8")
    err = os.fdopen(err_fd, "w", buffering=1, closefd=False, encoding="utf-8")
    log_fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    os.dup2(log_fd, 1)
    os.dup2(log_fd, 2)
    os.close(log_fd)
    saved_out, saved_err = sys.stdout, sys.stderr
    sys.stdout = os.fdopen(1, "w", buffering=1, closefd=False, encoding="utf-8")
    sys.stderr = os.fdopen(2, "w", buffering=1, closefd=False, encoding="utf-8")
    saved_rend = rend.out, rend.err
    rend.out, rend.err = term, err
    _LOG = path
    rend.debug(f"detailed log: {path}", log=str(path))
    try:
        yield path
    finally:
        with contextlib.suppress(Exception):  # restore must not be masked
            sys.stdout.flush()
            sys.stderr.flush()
        os.dup2(term_fd, 1)
        os.dup2(err_fd, 2)
        sys.stdout, sys.stderr = saved_out, saved_err
        rend.out, rend.err = saved_rend
        try:
            term.flush()
            err.flush()
            os.close(term_fd)
            os.close(err_fd)
        except OSError:
            pass
