#
# Copyright 2026 Tabsdata Inc.
#
"""Fan-out: a suite DIR is one instance/project per definition file (a "swim
lane"), each a normal single-lane `xp` child invoked with --format json so
its event stream is aggregated live under a running total across all lanes.

Failure policy: with --fail-fast the first lane to fail kills the others and
the run stops. Without it every lane is attempted; a multi-phase run (one-shot
over a dir) records the lanes that died against the phase and drops them from
the later phases, reporting them once at the end.
"""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from tabsdata_dev.common.core import batch as core_batch
from tabsdata_dev.common.core import proc

from . import state
from .reporter import child_env, emit_step, fs_token, rep, scratch
from .shell import dry_echo


def child_argv(*words: str) -> list[str]:
    """`tdd xp <words>`, through the dispatcher."""
    return proc.tool_argv(state.TOOL, *words)


def parallel(items: list, worker: Callable) -> None:
    """Run ``worker(item)`` concurrently (bounded by $TDD_PARALLELISM), FAIL
    FAST: the first worker to raise cancels what has not started and its
    exception is re-raised. Under --dry-run items run serially, so the printed
    command plan keeps a deterministic, paste-ready order."""
    items = list(items)
    if not items:
        return
    if state.run.dry_run or len(items) == 1:
        for item in items:
            worker(item)
        return
    with ThreadPoolExecutor(
        max_workers=min(len(items), core_batch.parallelism())
    ) as pool:
        futures = [pool.submit(worker, item) for item in items]
        error: BaseException | None = None
        for future in futures:
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 -- first one wins, re-raised
                if error is None:
                    error = exc
                    for pending in futures:
                        pending.cancel()
        if error is not None:
            raise error


def lane_of(base: str, member: str) -> str:
    """``'<base>_<lane>' -> '<lane>'``: the same token identifies a lane across
    phases keyed by instance name and then by project name."""
    return member[len(base) + 1 :] if member.startswith(base + "_") else member


def dispatch(
    label: str,
    argvs: list[tuple[str, list[str]]],
    phase: str | None = None,
    base: str | None = None,
    fatal: bool = True,
) -> list[str]:
    """Run each ``(lane, argv)`` as a child IN PARALLEL and aggregate their
    progress live. Returns the lanes that FAILED."""
    lanes = state.run.lanes
    track = (
        lanes is not None
        and phase is not None
        and base is not None
        and not state.run.fail_fast
    )
    skipped: list[tuple[str, str]] = []
    if track:
        live = []
        for lane, argv in argvs:
            died = lanes.get(lane_of(base, lane))  # type: ignore[union-attr]
            if died:
                skipped.append((lane, died))
            else:
                live.append((lane, argv))
        argvs = live
    rep().note(
        f"{label}: {len(argvs)} lane(s) in parallel"
        + (f", {len(skipped)} skipped" if skipped else "")
    )
    for lane, died in skipped:
        rep().note(f"{lane} skipped -- failed in phase '{died}'")
    if not argvs:
        rep().note("no lanes left -- every lane failed in an earlier phase")
        return []
    if state.run.dry_run:
        _dispatch_dry(argvs)
        return []

    lock = threading.Lock()
    totals: dict[str, int] = {}
    procs: dict[str, subprocess.Popen] = {}
    summaries: dict[str, dict] = {}
    tails: dict[str, list[str]] = {}
    # A lane's own error event: why it failed, which is what the console must
    # show -- its non-event output is usually empty (the child speaks json).
    errors: dict[str, list[str]] = {}
    failed: list[str] = []
    done = 0

    def on_event(lane: str, event: dict) -> None:
        nonlocal done
        kind = event.get("xp")
        if kind == "step":
            with lock:
                totals[lane] = max(totals.get(lane, 0), int(event.get("total") or 0))
                done += 1
                total = sum(totals.values())
                width = len(str(total))
                emit_step({**event, "lane": lane}, prefix=f"[{done:>{width}}/{total}] ")
            if not event.get("ok", True):
                rep().error(
                    f"FAILED lane {lane} - {event.get('action')} {event.get('path')} ({event.get('seconds')}s)",
                    str(event.get("step_error") or event.get("note") or ""),
                )
        elif kind == "summary":
            with lock:
                summaries[lane] = event
        if event.get("event") == "error":
            with lock:
                errors[lane] = _reason(str(event.get("message", "")))
        elif kind in ("note", "start", "dry-run"):
            rep().log(f"lane {lane} {kind}", str(event.get("message", "")))

    def run_lane(item) -> None:
        lane, argv = item
        log = scratch() / f"lane-{fs_token(lane)}.log"
        # stderr merged into stdout so a chatty child can never deadlock on a
        # full stderr pipe; non-event lines are separated back out by shape.
        p = subprocess.Popen(
            [*argv, "--format", "json"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(),
        )
        with lock:
            procs[lane] = p
            tails[lane] = []
        with log.open("w", encoding="utf-8") as fh:
            for raw in p.stdout:  # type: ignore[union-attr]
                line = raw.rstrip("\n")
                fh.write(raw)
                event = None
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = None
                if isinstance(event, dict) and event.get("event"):
                    on_event(lane, event)
                elif line.strip():
                    with lock:
                        tails[lane] = (tails[lane] + [line.strip()])[-8:]
        code = p.wait()
        summary = summaries.get(lane)
        if summary:
            rep().absorb_lane(lane, summary)
        if code == 0 and summary and summary.get("event") == "ok":
            return
        with lock:
            failed.append(lane)
            tail = errors.get(lane, []) + tails.get(lane, []) or [f"exit {code}"]
            rep().note(
                f"FAILED lane {lane} -- {len(tail)} line(s) of detail, full output in {log}",
                lane=lane,
                ok=False,
            )
            for line in tail:
                rep().note(f"    {line}", lane=lane)
        lane_errors = (
            Path(str(summary.get("scratch"))) / "errors.log"
            if summary and summary.get("scratch")
            else None
        )
        rep().error(
            f"FAILED lane {lane}",
            "\n".join(
                tail
                + [f"lane log: {log}"]
                + (
                    [f"lane errors: {lane_errors}"]
                    if lane_errors and lane_errors.exists()
                    else []
                )
            ),
        )
        if state.run.fail_fast:
            with lock:
                others = [q for name, q in procs.items() if name != lane]
            for q in others:
                q.terminate()

    # Lanes are processes, not steps of this run: every lane is joined, and the
    # policy below decides what a failure means.
    with ThreadPoolExecutor(
        max_workers=min(len(argvs), core_batch.parallelism())
    ) as pool:
        list(pool.map(run_lane, argvs))

    if not failed:
        return []
    if track:
        for lane in failed:
            lanes[lane_of(base, lane)] = phase  # type: ignore[index]
        rep().note(
            f"{len(failed)} lane(s) failed in '{phase}', dropped from the remaining phases: {', '.join(failed)}"
        )
        return failed
    if fatal:
        state.die(f"{len(failed)} of {len(argvs)} lane(s) failed: {', '.join(failed)}")
    return failed


def _reason(message: str) -> list[str]:
    """The lines of a lane's error that say why: its summary block (the run's
    totals, where its scratch dir is), which the lane log keeps, cut off."""
    lines = [ln.strip() for ln in message.splitlines() if ln.strip()]
    for i, line in enumerate(lines):
        if " - summary - " in line:
            return lines[:i]
    return lines


def _dispatch_dry(argvs: list[tuple[str, list[str]]]) -> None:
    """--dry-run fan-out: run the lanes SERIALLY and relay each child's bare
    command list verbatim, so the plan stays a deterministically ordered
    command sequence."""
    for lane, argv in argvs:
        # json, so only the commands (dry-run events) are relayed, not the lane's
        # own progress and summary lines.
        r = subprocess.run(
            [*argv, "--format", "json"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=child_env(),
        )
        for line in (r.stdout or "").splitlines():
            if line.strip():
                if line.startswith("{"):
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        event = {}
                    if event.get("xp") == "dry-run":
                        dry_echo(event.get("argv") or [event.get("message", "")])
                else:
                    print(line, flush=True)
        if r.returncode != 0:
            state.die(
                f"lane {lane} failed: {(r.stderr or r.stdout or '').strip().splitlines()[-1:] or ['(no output)']}"
            )
