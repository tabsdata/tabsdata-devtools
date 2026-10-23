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
stops launching once a task fails; ``--report FILE`` writes the run as JSON;
``--brief`` says one line per task: its start and a success's captured output
drop to ``debug`` (``--verbose`` shows them), a failure's output stays.

``TDD_PARALLELISM`` bounds the concurrency (default 10). The caller supplies
``spawn(argv)``: how a child is actually launched (through ``tdd-exe`` so it
lands in the right toolset, or ``python -m`` in a development run).

Or the caller passes no ``spawn`` and the batch launches each step itself,
**streamed**: every output line reaches ``Reporter.line`` as it is written, in
the task's ``cwd``, and each child runs as a tree of its own -- a POSIX process
group, a Windows job object -- so ``kill_on_fail`` and Ctrl-C stop the whole
tree, a pipeline included, not just its first process. A caller with its own
wording (``mexe``) subclasses ``Reporter``, passes ``workers`` and
``heaviest_first=False``, and keeps the summary with ``final=False``.
"""

from __future__ import annotations

import json
import os
import pathlib
import signal
import subprocess
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from . import proc, render

ENV_PARALLELISM = "TDD_PARALLELISM"
DEFAULT_PARALLELISM = 10

#: How long a killed tree gets to exit on SIGTERM -- a git releasing its lock
#: file -- before SIGKILL. Windows has no polite form: a job is terminated.
KILL_GRACE = 5.0

Spawn = Callable[[list[str]], subprocess.CompletedProcess]


@dataclass
class Task:
    name: str
    weight: int
    steps: list[list[str]] = field(default_factory=list)
    status: str = "pending"  # pending | ok | fail | skipped | aborted
    seconds: float = 0.0
    returncode: int | None = None
    output: str = ""
    cwd: pathlib.Path | None = None  # where a streamed step runs; None: here


def parallelism() -> int:
    raw = os.environ.get(ENV_PARALLELISM, "").strip()
    if raw.isdigit() and int(raw) >= 1:
        return int(raw)
    return DEFAULT_PARALLELISM


class Reporter:
    """What a run says. Every method is called under the run's lock, so a line
    is never torn and a task's block is never interleaved with another's. The
    defaults are the batch's own lines; `line` says nothing, since a streamed
    task's output is reported whole at its end."""

    def __init__(
        self, out: render.Renderer, label: str, role: str, *, brief: bool = False
    ):
        self.out = out
        self.label = label
        self.role = role
        self.brief = brief

    def begin(self, tasks: list[Task], workers: int, heaviest_first: bool) -> None:
        self.out.info(
            f"{self.label}: {len(tasks)} {self.role}(s), parallel x{workers}"
            + (", heaviest first" if heaviest_first else ""),
            count=len(tasks),
            parallelism=workers,
        )

    def start(self, task: Task) -> None:
        (self.out.debug if self.brief else self.out.info)(
            f"▶ {self.label} {task.name} (weight {task.weight})", task=task.name
        )

    def line(self, task: Task, line: str) -> None:
        pass

    def end(self, task: Task, done: int, total: int) -> None:
        head = f"[{done}/{total}] {task.name} {task.status.upper()} ({task.seconds}s)"
        body = "\n".join(f"        {line}" for line in task.output.splitlines())
        fields = {
            "task": task.name,
            "status": task.status,
            "seconds": task.seconds,
            "output": task.output,
        }
        if task.status != "ok":
            self.out.warn(head + ("\n" + body if body else ""), **fields)
        elif not self.brief:
            self.out.info(head + ("\n" + body if body else ""), **fields)
        else:
            self.out.info(head, **fields)
            if body:
                self.out.debug(body, task=task.name)


# ------------------------------------------------------------ process trees
class Tree:
    """A streamed child and everything it starts, stopped together.

    Killing the child alone is not enough: the shell of `a | b` dies and `a`
    and `b` live on, holding the output pipe open, so the reader never sees
    its end. POSIX: the child leads a session of its own and the group is
    signalled. Windows: the child is put in a job object, and the job is
    terminated -- `kill()` there stops one process. A process the child starts
    in the instant before it joins the job escapes it; nothing short of
    creating it suspended closes that window, and Popen cannot.
    """

    def __init__(self, argv: list[str], cwd, env):
        group = (
            {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
            if os.name == "nt"
            else {"start_new_session": True}
        )
        self.proc = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            # Parallel children cannot share one terminal's input.
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            # Merged: the order within a task is the order it was written in,
            # and a chatty stderr can never fill its pipe unread.
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **group,
        )
        self.job = proc.Job(self.proc.pid)
        self.killed = False

    def kill(self) -> None:
        self.killed = True
        try:
            if self.job.terminate():
                return
            if os.name == "nt":
                self.proc.kill()
            else:
                os.killpg(self.proc.pid, signal.SIGTERM)
                timer = threading.Timer(KILL_GRACE, self._kill_hard)
                timer.daemon = True
                timer.start()
        except OSError:
            pass  # already gone

    def _kill_hard(self) -> None:
        try:
            os.killpg(self.proc.pid, signal.SIGKILL)
        except OSError:
            pass

    def close(self) -> None:
        self.job.close()


# ------------------------------------------------------------------- the run
def execute(
    label: str,
    tasks: list[Task],
    spawn: Spawn | None,
    out: render.Renderer,
    *,
    role: str = "target",
    fail_fast: bool = False,
    report_path: str | None = None,
    final: bool = True,
    workers: int | None = None,
    heaviest_first: bool = True,
    kill_on_fail: bool = False,
    env: dict[str, str] | None = None,
    reporter: Reporter | None = None,
    brief: bool = False,
) -> int:
    """Run `tasks`; return 0 iff every task succeeded.

    `final` emits the summary as the run's ``ok``/``error``; a caller that has
    more to do afterwards passes False and reports the outcome itself, so the
    stream still ends in exactly one of them.

    `spawn` None streams (see the module doc): each step is launched here, in
    `task.cwd` with `env`, and `kill_on_fail` -- `fail_fast` that also stops
    what is running -- works only then, since a `spawn` child is out of reach.
    A streamed argv is launched as given, not through `proc.run`: the caller
    vouches for its binary. `workers` overrides `TDD_PARALLELISM`.
    """
    workers = workers or parallelism()
    if heaviest_first:
        tasks.sort(key=lambda t: (-t.weight, t.name))
    say = reporter or Reporter(out, label, role, brief=brief)
    lock = threading.Lock()
    abort = threading.Event()
    trees: set[Tree] = set()
    pending = list(tasks)
    done = 0
    with lock:
        say.begin(tasks, workers, heaviest_first)

    def stop_all() -> None:
        abort.set()
        with lock:
            running = list(trees)
        for tree in running:
            tree.kill()

    def spawned(task: Task, step: list[str]) -> tuple[int, str]:
        cp = spawn(step)  # type: ignore[misc]
        return cp.returncode, ((cp.stdout or "") + (cp.stderr or "")).strip()

    def streamed(task: Task, step: list[str]) -> tuple[int, str]:
        tree = Tree(step, task.cwd, env)
        with lock:
            trees.add(tree)
        if abort.is_set():  # the abort came while this was starting
            tree.kill()
        lines: list[str] = []
        try:
            for raw in tree.proc.stdout:  # type: ignore[union-attr]
                line = raw.rstrip("\r\n")
                lines.append(line)
                with lock:
                    say.line(task, line)
            rc = tree.proc.wait()
        finally:
            with lock:
                trees.discard(tree)
            tree.close()
        if tree.killed and rc != 0:
            task.status = "aborted"
        return rc, "\n".join(lines)

    def work(task: Task) -> None:
        nonlocal done
        with lock:
            say.start(task)
        started = time.monotonic()
        chunks: list[str] = []
        rc = 0
        run_step = spawned if spawn is not None else streamed
        for step in task.steps:
            if abort.is_set() and kill_on_fail:
                task.status = "aborted"
                break
            rc, said = run_step(task, step)
            if said:
                chunks.append(said)
            if rc != 0:
                break  # stop this task's chain on the first failing step
        task.seconds = round(time.monotonic() - started, 2)
        task.returncode = rc
        task.output = "\n".join(chunks)
        if task.status != "aborted":
            task.status = "ok" if rc == 0 else "fail"
        with lock:
            done += 1
            say.end(task, done, len(tasks))
        if task.status == "fail" and (fail_fast or kill_on_fail):
            if kill_on_fail:
                stop_all()
            else:
                abort.set()

    def worker() -> None:
        while True:
            with lock:
                if not pending:
                    return
                task = pending.pop(0)
            if abort.is_set():
                task.status = "skipped"
                continue
            work(task)

    t_start = time.monotonic()
    threads = [
        threading.Thread(target=worker, daemon=True)
        for _ in range(max(1, min(workers, len(tasks))))
    ]
    for t in threads:
        t.start()
    try:
        # Joined with a timeout so Ctrl-C reaches this thread. A streamed
        # child is in a tree of its own and never sees the terminal's SIGINT,
        # so this is where it is stopped.
        while any(t.is_alive() for t in threads):
            for t in threads:
                t.join(0.2)
    except KeyboardInterrupt:
        stop_all()
        for t in threads:
            t.join()
        raise
    total = round(time.monotonic() - t_start, 1)
    finished = tasks
    ok = sum(1 for t in finished if t.status == "ok")
    failed = sum(1 for t in finished if t.status == "fail")
    skipped = sum(1 for t in finished if t.status == "skipped")
    aborted = sum(1 for t in finished if t.status == "aborted")
    if report_path:
        _write_report(report_path, label, workers, total, finished)
        out.info(f"wrote run report to {report_path}", report=report_path)
    tail = f", {skipped} skipped" if skipped else ""
    tail += f", {aborted} aborted" if aborted else ""
    summary = f"{label}: {ok} ok, {failed} failed{tail} in {total}s"
    fields = {"ok": ok, "failed": failed, "skipped": skipped, "seconds": total}
    if aborted:
        fields["aborted"] = aborted
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
    return 0 if failed == 0 and aborted == 0 else 1


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
        "started": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "parallelism": workers,
        "total_seconds": total,
        "ok": sum(1 for t in tasks if t.status == "ok"),
        "failed": sum(1 for t in tasks if t.status == "fail"),
        "skipped": sum(1 for t in tasks if t.status == "skipped"),
        "aborted": sum(1 for t in tasks if t.status == "aborted"),
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
