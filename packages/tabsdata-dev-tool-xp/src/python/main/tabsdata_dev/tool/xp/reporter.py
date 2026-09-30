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

    container-connectors/db2 - [ 4/17] - create-collection - xp_..._db2/db2_in -   1.42s

``--format view`` shows those lines; ``--format json`` prints the events, which
is exactly what the lane dispatcher reads back to aggregate N lanes live. The
DETAIL -- every command and its output -- goes to ``<scratch>/run.log``, never
to the console; the failures alone go to ``<scratch>/errors.log`` (created on
the first failure, so its existence answers "did this run go wrong"); the whole
run is written to ``<scratch>/report.json`` at the end and becomes the fields
of the run's final ``ok``/``error``.

Every run gets ONE scratch directory under ``/tmp/tdd-xp/``, announced at
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
from collections.abc import Iterable, Iterator
from typing import TextIO
from contextlib import contextmanager
from datetime import datetime, timezone

from tabsdata_dev.common.core import render

from . import state

# Stamped ONCE at process start and reused for every name this run derives, so
# all domains a single invocation creates share one timestamp.
RUN_TS = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
SCRATCH_ROOT = render.LOG_DIR / "tdd-xp"

# Progress-line column widths (view format). The path ends the line: it is as
# long as its names, so nothing after it could line up. The note column fits
# the one-word outcomes steps note ('exists', 'absent', 'dry-run', 'disabled'),
# and a run that knows its notes beforehand widens it to the longest (see
# Reporter.reserve); a note it could not know pushes its own line's path on.
_W_ACTION = 18
# What became of a step, as its status column says it, and in what colour.
PASSED, FAILED, DRY_RUN = "passed", "failed", "dry-run"
_STATUS_PAINTS = {PASSED: "soft-green", FAILED: "soft-red", DRY_RUN: "soft-orange"}
_W_STATUS = max(map(len, _STATUS_PAINTS))
_W_NOTE = 8
# A step taking at least this long has its time painted, to find it in a run.
SLOW_STEP_SECONDS = 60.0


def fs_token(value: str) -> str:
    """`value` reduced to a filesystem-safe path segment."""
    return re.sub(r"[^A-Za-z0-9._-]+", "_", value).strip("_") or "run"


def scratch_init(label: str) -> pathlib.Path:
    """Create (once) and return this run's scratch dir. Under $_TDD_XP_SCRATCH --
    i.e. in a fan-out child -- it is a `<label>` subdir of the parent's tree;
    standalone it is a fresh `/tmp/tdd-xp/<ts>_<label>_<uniq>`."""
    if state.run.scratch is not None:
        return state.run.scratch
    inherited = os.environ.get(state.SCRATCH_ENV)
    if inherited and os.environ.get(state.SCRATCH_PARENT_ENV) != str(os.getppid()):
        # Not handed down by a running parent: a stale export in the shell.
        state.run.out.warn(
            f"{state.SCRATCH_ENV} is set in the environment but not by a parent xp run;"
            " ignored (it is private to xp's fan-out)",
            xp="note",
        )
        inherited = None
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
    """Environment for a fan-out child: this run's scratch dir as its root, and
    this pid as the proof it came from a parent."""
    return {
        **os.environ,
        state.SCRATCH_ENV: str(scratch()),
        state.SCRATCH_PARENT_ENV: str(os.getpid()),
    }


def strip_ansi(text: str) -> str:
    return re.sub(r"\033\[[0-9;]*m", "", text)


def exc_text(exc: BaseException) -> str:
    """A failed step's error text; a die() carries its message."""
    return f"{type(exc).__name__}: {exc}" if str(exc) else type(exc).__name__


class Reporter:
    """Incremental progress + detail log for one xp run (one suite)."""

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
        # Steps reserved up front that the phases' own plans draw on.
        self.reserved = 0
        self.note_width = _W_NOTE
        # Set by a lane fan-out, which re-renders its lanes' steps: the suite
        # column as wide as the longest lane's label, and the lanes' own [n/m]
        # as wide as the widest lane's -- 0 leaves each line its own.
        self.suite_width = 0
        self.counter_width = 0
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
        run. Commands plan a phase at a time (oneshot plans four); a phase of a
        run reserved up front draws on the reservation instead."""
        with self._lock:
            taken = min(n, self.reserved)
            self.reserved -= taken
            self.total += n - taken

    def reserve(self, n: int, notes: Iterable[str] = ()) -> None:
        """Declare a whole run of `n` steps before any of its phases plans its
        own -- a suite's, live steps included, which no phase plans -- so the
        [N/M] denominator is the run's from its first step. `notes` are the
        notes its steps are known to carry, which the note column is as wide
        as."""
        with self._lock:
            self.total += n
            self.reserved += n
            self.note_width = max(self.note_width, *map(len, notes), 0)

    def widen(
        self, notes: Iterable[str] = (), suites: Iterable[str] = (), total: int = 0
    ) -> None:
        """Make room, before they run, for steps this run will re-render but
        not plan -- its lanes': their notes, their suite labels, and the
        largest of their totals."""
        with self._lock:
            self.note_width = max(self.note_width, *map(len, notes), 0)
            self.suite_width = max(self.suite_width, *map(len, suites), 0)
            self.counter_width = max(
                self.counter_width, len(str(total)) if total else 0
            )

    def release(self) -> None:
        """End the reservation: what it held stays in the total, and the steps
        planned after it add to it."""
        with self._lock:
            self.reserved = 0

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
                "status": FAILED
                if not ok
                else DRY_RUN
                if state.run.dry_run
                else PASSED,
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


def render_step(
    event: dict,
    stream: TextIO | None = None,
    note_width: int = _W_NOTE,
    suite_width: int = 0,
    counter_width: int = 0,
) -> str:
    """One progress line: ``suite - [N/M] - action - seconds - status - note -
    path``, the note blank where the step has none. The suite and the counter
    are as wide as they are, or as `suite_width` and `counter_width` say when
    lines of several lanes share a console. Painted for `stream` when
    it is a terminal, a soft colour a column: the suite yellow, the counter
    magenta, the action cyan, the time blue, orange for a slow step, the
    status green when the step passed, red when it failed and orange on a dry
    run, the note violet and the path brown."""

    def paint(name: str, text: str) -> str:
        return render.paint(name, text, stream) if stream is not None else text

    status = event.get("status") or (PASSED if event.get("ok", True) else FAILED)
    width = max(len(str(event["total"])), counter_width)
    suite = paint("soft-yellow", f"{event['suite']:<{suite_width}}")
    # Right-aligned whole, so a lane of fewer steps ends where the widest does.
    count = f"[{event['n']:>{width}}/{event['total']}]"
    counter = paint("soft-magenta", f"{count:>{2 * width + 3}}")
    action = paint("soft-cyan", f"{event['action']:<{_W_ACTION}}")
    slow = event["seconds"] >= SLOW_STEP_SECONDS
    seconds = paint("soft-orange" if slow else "soft-blue", f"{event['seconds']:7.2f}s")
    outcome = paint(
        _STATUS_PAINTS.get(status, "soft-red"), f"{status.upper():<{_W_STATUS}}"
    )
    note = paint("soft-violet", f"{event.get('note') or '':<{note_width}}")
    path = paint("soft-brown", event["path"])
    return f"{suite} - {counter} - {action} - {seconds} - {outcome} - {note} - {path}"


def emit_step(event: dict, prefix: str = "") -> None:
    """A step as an event: info when it passed, warn when it failed; the
    rendered line is the message, the step is the fields. A step re-emitted
    from a lane arrives as the child's whole event, model keys included; those
    are the renderer's to write, not fields."""
    out = state.run.out
    stream = out.err if out.fmt == "view" else None
    reporter = state.run.reporter
    if reporter is None:
        text = prefix + render_step(event, stream)
    else:
        text = prefix + render_step(
            event,
            stream,
            reporter.note_width,
            reporter.suite_width,
            reporter.counter_width,
        )
    if event.get("step_error"):
        detail = "\n".join(
            f"        {line}" for line in str(event["step_error"]).splitlines()
        )
        text += "\n" + (render.paint("soft-red", detail, stream) if stream else detail)
    fields = {
        k: v
        for k, v in event.items()
        if k not in ("command", "event", "message", "log")
    }
    (state.run.out.info if event.get("ok", True) else state.run.out.warn)(
        text, **fields
    )


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
