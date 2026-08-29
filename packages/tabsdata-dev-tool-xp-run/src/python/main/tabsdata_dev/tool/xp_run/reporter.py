#
# Copyright 2026 Tabsdata Inc.
#
"""Progress, the scratch dir and the report -- what tdx-xp called its Reporter,
speaking the event model of docs/command-cli-guidelines.md.

One STEP is one unit of a suite's work: a domain, the project, a collection
group, a collection, a function registration, a trigger, the monitor wait. A
command declares how many steps it is about to run (``plan``) and wraps each in
``step``, which times it and reports it AS IT FINISHES, as an ``info`` event
(``warn`` when it failed) whose message is the progress line and whose fields
carry the structured step (``xp: "step"``):

    connectors/db2 - [ 4/17] - create-collection - xp_..._db2/db2_in -   1.42s

``--format view`` shows those lines; ``--format json`` prints the events, which
is exactly what the lane dispatcher reads back to aggregate N lanes live. The
DETAIL -- every command and its output -- goes to ``<scratch>/run.log``, never
to the console; the failures alone go to ``<scratch>/errors.log`` (created on
the first failure, so its existence answers "did this run go wrong"); the whole
run is written to ``<scratch>/report.json`` at the end and becomes the fields
of the run's final ``ok``/``error``.

Every run gets ONE scratch directory under ``/tmp/tdd-xp-run/``, announced at
startup and not deleted: the domain manifests it authors, the logs, the report,
and -- for a fanned-out run -- one subdir per lane all land there.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import tempfile
import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timezone

from tabsdata_dev.common.core import render

from . import state

# Stamped ONCE at process start and reused for every name this run derives, so
# all domains a single invocation creates share one timestamp.
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
SCRATCH_ROOT = render.LOG_DIR / "tdd-xp-run"

# Progress-line column widths (view format).
_W_ACTION = 18
_W_PATH = 46


def fs_token(value: str) -> str:
    """`value` reduced to a filesystem-safe path segment."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "run"


def scratch_init(label: str) -> pathlib.Path:
    """Create (once) and return this run's scratch dir. Under $TDD_XP_SCRATCH --
    i.e. in a fan-out child -- it is a `<label>` subdir of the parent's tree;
    standalone it is a fresh `/tmp/tdd-xp-run/<ts>_<label>_<uniq>`."""
    if state.run.scratch is not None:
        return state.run.scratch
    inherited = os.environ.get(state.SCRATCH_ENV)
    if inherited:
        dest = pathlib.Path(inherited) / fs_token(label)
        dest.mkdir(parents=True, exist_ok=True)
    else:
        SCRATCH_ROOT.mkdir(parents=True, exist_ok=True)
        dest = pathlib.Path(
            tempfile.mkdtemp(dir=SCRATCH_ROOT, prefix=f"{RUN_TS}_{fs_token(label)}_")
        )
    state.run.scratch = dest
    return dest


def scratch() -> pathlib.Path:
    """This run's scratch dir, created on first use."""
    if state.run.scratch is None:
        return scratch_init(state.TOOL)
    return state.run.scratch


def child_env() -> dict:
    """Environment for a fan-out child: this run's scratch dir as its root."""
    return {**os.environ, state.SCRATCH_ENV: str(scratch())}


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def exc_text(exc: BaseException) -> str:
    """A failed step's error text; a die() carries its message."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


class Reporter:
    """Incremental progress + detail log for one xp-run run (one suite)."""

    def __init__(
        self, suite: str, command: str, target: str | None, dest: pathlib.Path
    ):
        self.suite = suite
        self.command = command
        self.target = target
        self.scratch = dest
        self.log_path = dest / "run.log"
        self.errors_path = dest / "errors.log"  # written only if something fails
        self.total = 0
        self.done = 0
        self.failed = 0
        self.steps: list[dict] = []
        # Extra top-level keys for the report -- bench adds its phase metrics.
        self.extra: dict = {}
        # Summaries of the lanes this run dispatched (empty for a single suite).
        self.lanes: dict[str, dict] = {}
        self.started = datetime.now(timezone.utc)
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()

    # -- planning & steps --
    def plan(self, n: int) -> None:
        """Declare `n` more steps, so the [N/M] denominator is known before they
        run. Commands plan a phase at a time (oneshot plans four)."""
        with self._lock:
            self.total += n

    @contextmanager
    def step(self, action: str, path: str) -> Iterator[dict]:
        """Time one step and report it when the body leaves -- as a failure if
        the body raised, then re-raising so the caller's fail-fast still bites.
        The yielded dict's ``note`` is shown after the timing, for a one-word
        outcome the action alone does not convey ('exists', 'absent')."""
        rec: dict = {"note": ""}
        t = time.perf_counter()
        try:
            yield rec
        except BaseException as exc:  # noqa: BLE001 -- reported, then re-raised
            self._record(
                action,
                path,
                time.perf_counter() - t,
                False,
                rec.get("note", ""),
                exc_text(exc),
            )
            raise
        self._record(
            action, path, time.perf_counter() - t, True, rec.get("note", ""), ""
        )

    def step_done(
        self,
        action: str,
        path: str,
        seconds: float,
        ok: bool,
        note: str = "",
        error: str = "",
    ) -> None:
        """Report a step that has ALREADY run and been timed elsewhere -- a domain
        the `tdd domain --manifest` child provisioned and reported the cost of."""
        self._record(action, path, seconds, ok, note, error)

    def _record(
        self, action: str, path: str, seconds: float, ok: bool, note: str, error: str
    ) -> None:
        with self._lock:
            self.done += 1
            if not ok:
                self.failed += 1
            event = {
                "xp": "step",
                "suite": self.suite,
                "n": self.done,
                "total": max(self.total, self.done),
                "action": action,
                "path": path,
                "seconds": round(seconds, 2),
                "ok": ok,
                "note": note,
                "step_error": error,
            }
            self.steps.append(event)
            emit_step(event)
        if not ok:
            self.error(f"FAILED {action} {path} ({round(seconds, 2)}s)", error or note)

    # -- emission --
    def note(self, text: str, **fields) -> None:
        """A line that is not a step -- a heading, or where a file was written."""
        state.run.out.info(
            f"{self.suite} - {text}", xp="note", suite=self.suite, **fields
        )

    # -- detail log --
    def log(self, header: str, body: str = "") -> None:
        """Append one entry to run.log -- the full command, its output."""
        self._append(self.log_path, header, body)

    def error(self, header: str, body: str = "") -> None:
        """Append one entry to errors.log -- a failed step, or an error that would
        otherwise only reach the console. The first entry writes a heading naming
        the run and pointing at run.log."""
        if not self.errors_path.exists():
            self._append(
                self.errors_path,
                f"{state.TOOL} {self.command} {self.target or ''} -- errors only",
                f"suite: {self.suite}\nfull detail: {self.log_path}",
            )
        self._append(self.errors_path, strip_ansi(header), strip_ansi(body))

    def _append(self, path: pathlib.Path, header: str, body: str) -> None:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        with self._lock:
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"\n=== {stamp} {header} ===\n")
                if body:
                    fh.write(body.rstrip("\n") + "\n")

    def absorb_lane(self, lane: str, summary: dict) -> None:
        """Fold a dispatched lane's summary into this run's."""
        with self._lock:
            self.lanes[lane] = summary

    # -- wrap-up --
    def summary(self) -> dict:
        doc = {
            "suite": self.suite,
            "xp_command": self.command,
            "target": self.target,
            "started_at": self.started.isoformat(),
            "seconds": round(time.perf_counter() - self._t0, 2),
            "steps": len(self.steps),
            "ok": len(self.steps) - self.failed,
            "failed": self.failed,
            "scratch": str(self.scratch),
            "run_log": str(self.log_path),
        }
        if self.errors_path.exists():
            doc["errors"] = str(self.errors_path)
        if self.lanes:
            doc["lanes_total"] = len(self.lanes)
            doc["lane_steps"] = sum(
                int(s.get("steps") or 0) for s in self.lanes.values()
            )
            doc["lane_failed"] = sum(
                int(s.get("failed") or 0) for s in self.lanes.values()
            )
            doc["lanes"] = self.lanes
        return doc

    def close(self, report: str | None = None) -> dict:
        """Write report.json (and a copy at --report FILE) and return the summary
        document -- the fields of the run's final event, emitted by the caller.
        Called even when the run FAILED, so a partial report survives."""
        doc = {**self.summary(), **self.extra}
        doc["detail"] = self.steps
        text = json.dumps(doc, indent=2, default=str) + "\n"
        (self.scratch / "report.json").write_text(text, encoding="utf-8")
        if report:
            pathlib.Path(report).write_text(text, encoding="utf-8")
        return doc


def render_step(event: dict) -> str:
    """One progress line: ``suite - [N/M] - action - path - seconds``."""
    width = len(str(event["total"]))
    note = f"  ({event['note']})" if event.get("note") else ""
    mark = "" if event.get("ok", True) else "  FAILED"
    return (
        f"{event['suite']} - [{event['n']:>{width}}/{event['total']}] - "
        f"{event['action']:<{_W_ACTION}} - {event['path']:<{_W_PATH}} - "
        f"{event['seconds']:6.2f}s{note}{mark}"
    )


def emit_step(event: dict, prefix: str = "") -> None:
    """A step as an event: info when it passed, warn when it failed; the
    rendered line is the message, the step is the fields."""
    text = prefix + render_step(event)
    if event.get("step_error"):
        text += "\n" + "\n".join(
            f"        {line}" for line in str(event["step_error"]).splitlines()
        )
    (state.run.out.info if event.get("ok", True) else state.run.out.warn)(text, **event)


def render_summary(doc: dict) -> str:
    steps = doc["steps"] + int(doc.get("lane_steps") or 0)
    failed = doc["failed"] + int(doc.get("lane_failed") or 0)
    if failed:
        head = f"{steps - failed} ok, {failed} failed"
    elif doc.get("errors"):
        head = f"{steps} ok, run failed"
    else:
        head = "all ok"
    lanes = f" over {doc['lanes_total']} lane(s)" if doc.get("lanes_total") else ""
    errors = f"\nerrors: {doc['errors']}" if doc.get("errors") else ""
    return f"{doc['suite']} - summary - {steps} step(s){lanes}, {head} in {doc['seconds']}s - {doc['scratch']}{errors}"


def rep() -> Reporter:
    """The active reporter (a bare one, reporting nowhere in particular, if no
    command opened it -- so helper code can log unconditionally)."""
    if state.run.reporter is None:
        state.run.reporter = Reporter(state.TOOL, state.TOOL, None, scratch())
    return state.run.reporter


def say(text: str) -> None:
    """A human line that is not a step: through the run's reporter when one is
    open, else a plain info event (the pointer-only verbs open no reporter)."""
    if state.run.reporter is not None:
        state.run.reporter.note(text)
    else:
        state.run.out.info(text, xp="note")


@contextmanager
def reporting(
    args, command: str, target: str | None, suite: str | None = None
) -> Iterator[Reporter]:
    """Open the run's reporter for `command`, writing the report on the way out
    (success or failure) and leaving it in ``state.run.summary`` for the final
    event. A nested in-process call finds it already open and reports into it."""
    if state.run.reporter is not None:
        yield state.run.reporter
        return
    label = suite or target or command
    dest = scratch_init(f"{command}_{label}")
    state.run.reporter = Reporter(label, command, target, dest)
    state.run.out.info(
        f"scratch {dest}", xp="start", xp_command=command, scratch=str(dest)
    )
    try:
        yield state.run.reporter
    finally:
        state.run.summary = state.run.reporter.close(getattr(args, "report", None))
        state.run.reporter = None
