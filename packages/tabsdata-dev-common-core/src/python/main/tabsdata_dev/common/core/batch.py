#
# Copyright 2026 Tabsdata Inc.
#

"""Run many child invocations in parallel and report through the renderer.

A ``Task`` is a named unit of work made of one or more ``steps`` -- each a full
child argv -- run in order, stopping at the first failing step. ``execute``
runs the tasks with bounded concurrency, heaviest ``weight`` first, each child a
separate process (full isolation, safe with fork- and thread-unsafe native
clients), and speaks the event model: an ``info`` when a task starts, an
``info``/``warn`` when it ends (with its captured output), and one ``ok`` or
``error`` summary -- unless the caller asks to emit its own. ``--fail-fast``
stops launching once a task fails; ``--report FILE`` writes the run as JSON.

``TDD_PARALLELISM`` bounds the concurrency (default 10). The caller supplies
``spawn(argv)``: how a child is actually launched (through ``tdd-exe`` so it
lands in the right toolset, or ``python -m`` in a development run).
"""

from __future__ import annotations

import json
import os
import pathlib
import subprocess
import threading
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timezone

from . import render

ENV_PARALLELISM = "TDD_PARALLELISM"
DEFAULT_PARALLELISM = 10

Spawn = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass
class Task:
    name: str
    weight: int
    steps: list[list[str]] = field(default_factory=list)
    status: str = "pending"  # pending | ok | fail | skipped
    seconds: float = 0.0
    returncode: int | None = None
    output: str = ""


def parallelism() -> int:
    raw = os.environ.get(ENV_PARALLELISM, "").strip()
    if raw.isdigit() and int(raw) >= 1:
        return int(raw)
    return DEFAULT_PARALLELISM


def execute(
    label: str,
    tasks: list[Task],
    spawn: Spawn,
    out: render.Renderer,
    *,
    role: str = "target",
    fail_fast: bool = False,
    report_path: str | None = None,
    final: bool = True,
) -> int:
    """Run `tasks`; return 0 iff every task succeeded.

    `final` emits the summary as the run's ``ok``/``error``; a caller that has
    more to do afterwards passes False and reports the outcome itself, so the
    stream still ends in exactly one of them.
    """
    workers = parallelism()
    tasks.sort(key=lambda t: (-t.weight, t.name))
    out.info(
        f"{label}: {len(tasks)} {role}(s), parallel x{workers}, heaviest first",
        count=len(tasks),
        parallelism=workers,
    )
    lock = threading.Lock()
    abort = threading.Event()
    done = 0

    def work(task: Task) -> Task:
        nonlocal done
        if abort.is_set():
            task.status = "skipped"
            return task
        with lock:
            out.info(f"▶ {label} {task.name} (weight {task.weight})", task=task.name)
        started = time.monotonic()
        chunks: list[str] = []
        rc = 0
        for step in task.steps:
            cp = spawn(step)
            chunks.append(((cp.stdout or "") + (cp.stderr or "")).strip())
            rc = cp.returncode
            if rc != 0:
                break  # stop this task's chain on the first failing step
        task.seconds = round(time.monotonic() - started, 2)
        task.returncode = rc
        task.output = "\n".join(c for c in chunks if c)
        task.status = "ok" if rc == 0 else "fail"
        with lock:
            done += 1
            head = f"[{done}/{len(tasks)}] {task.name} {task.status.upper()} ({task.seconds}s)"
            body = "\n".join(f"        {line}" for line in task.output.splitlines())
            text = head + ("\n" + body if body else "")
            fields = dict(
                task=task.name,
                status=task.status,
                seconds=task.seconds,
                output=task.output,
            )
            (out.info if task.status == "ok" else out.warn)(text, **fields)
            if task.status == "fail" and fail_fast:
                abort.set()
        return task

    t_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=workers) as ex:
        finished = list(ex.map(work, tasks))
    total = round(time.monotonic() - t_start, 1)
    ok = sum(1 for t in finished if t.status == "ok")
    failed = sum(1 for t in finished if t.status == "fail")
    skipped = sum(1 for t in finished if t.status == "skipped")
    if report_path:
        _write_report(report_path, label, workers, total, finished)
        out.info(f"wrote run report to {report_path}", report=report_path)
    tail = f", {skipped} skipped" if skipped else ""
    summary = f"{label}: {ok} ok, {failed} failed{tail} in {total}s"
    fields = dict(ok=ok, failed=failed, skipped=skipped, seconds=total)
    if final:
        if failed:
            recap = "\n".join(
                f"    FAILED {t.name}"
                + (f"  {t.output.splitlines()[-1]}" if t.output else "")
                for t in finished
                if t.status == "fail"
            )
            out.error(
                summary + ("\n" + recap if recap else ""),
                details=_details(finished),
                **fields,
            )
        else:
            out.ok(summary, **fields)
    return 0 if failed == 0 else 1


def _details(tasks: list[Task]) -> str:
    return "\n\n".join(
        f"== {t.name} {t.status} rc={t.returncode} {t.seconds}s\n{t.output}"
        for t in tasks
    )


def _write_report(
    path: str, label: str, workers: int, total: float, tasks: list[Task]
) -> None:
    report = {
        "label": label,
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "parallelism": workers,
        "total_seconds": total,
        "ok": sum(1 for t in tasks if t.status == "ok"),
        "failed": sum(1 for t in tasks if t.status == "fail"),
        "skipped": sum(1 for t in tasks if t.status == "skipped"),
        "tasks": [
            {
                "name": t.name,
                "weight": t.weight,
                "status": t.status,
                "seconds": t.seconds,
                "returncode": t.returncode,
                "output": t.output,
            }
            for t in tasks
        ],
    }
    p = pathlib.Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(report, indent=2), encoding="utf-8")
