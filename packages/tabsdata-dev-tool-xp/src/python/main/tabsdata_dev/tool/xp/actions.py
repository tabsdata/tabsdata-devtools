#
# Copyright 2026 Tabsdata Inc.
#
"""Actions: a suite's ``actions`` stages, every one of them one script.

An entry is one of five steps or four blocks (``models.Action``)::

    "actions": [
      {"tdd": {"name": "seed", "tool": "domain", "command": "sentinel-data",
               "options": ["--domain", "${xp:name(pg)}", "--key", "k"]}},
      {"background": {"name": "churn", "tags": ["churn"], "actions": [
        {"loop": {"name": "cycle", "repeat": 20, "actions": [
          {"tdd": {"name": "change", "tool": "domain", "command": "modify-data",
                   "options": ["--domain", "${xp:name(pg)}"]}},
          {"sleep": {"name": "pause", "time": "1s"}}]}}]}},
      {"wait": {"name": "settled", "for": ["churn"]}},
      {"python": {"name": "verify", "script": "scripts/check.py", "params": [...]}}
    ]

``tdd`` runs ``tdd-exe TOOL COMMAND OPTIONS...``, any Python tool as typed;
``exe`` any program on the PATH; ``python`` ``uv run --no-project --with REQ...
SCRIPT PARAMS...`` from the suite dir, with the ``tdd`` module on its
PYTHONPATH (``from tdd import tdd``), ``tdd-exe`` on its PATH and the run's
``XP_*`` in its environment -- a stdout line ``xp-note: <text>`` is its step's
note. ``sleep`` pauses, ``wait`` holds until the entries it names have
finished. ``background`` starts its actions and the script goes on;
``parallel`` runs its actions side by side (``lanes`` at a time, 0 all) and
joins them; ``loop`` runs them ``repeat`` times, each pass complete when
everything it started has finished; ``timeout`` runs them for at most
``time``, then fails the run (``stop_on_timeout``, the default) or goes on and
leaves them running.

Every actions stage of a suite is one script with one scope: a background
block keeps running through the stages after it, and a wait in a later stage
finds it. Names are the suite's; a wait reaches back, not in (checked when the
suite is read). The first failure anywhere -- a step without
``continue_on_fail`` -- stops the script: what is running finishes its step,
nothing new starts, and that failure is the run's. ``continue_on_fail`` reports
the failure and goes on; the run fails at its end. What is still running when
the run ends -- a timed-out block left to run, say -- is killed: every step
runs in a process group of its own, which gets SIGTERM and, after a grace,
SIGKILL.

Tags pick what runs: an entry's are its own and every enclosing block's.
``--tags A,B`` runs the steps with A or B, ``--skip-tags C,D`` those with
neither, both together those that pass both; a block runs when a step inside
it does, and only those steps. A wait on an entry that does not run is
satisfied at once. ``--no-actions`` runs none.

A step's output goes to run.log as it comes, each line prefixed with its
label (``cycle 2/20 > change``), so steps side by side stay readable.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import signal
import subprocess
import threading
import time
from collections import deque
from collections.abc import Iterator
from concurrent.futures import Future
from concurrent.futures import wait as wait_futures
from dataclasses import dataclass, field
from importlib.resources import files

from tabsdata_dev.common.core import proc

from . import shell, state, work
from .models import Action, Instance
from .reporter import rep

#: How many of a failed step's last output lines make its error.
TAIL_LINES = 20
#: A stdout line so marked is a python step's note; `tdd.note()` prints one.
NOTE_MARK = "xp-note:"
#: A note is one column of a progress line, not a report: longer is cut.
NOTE_MAX = 160
#: How long a killed step's process group has after SIGTERM before SIGKILL.
KILL_GRACE = 5.0
#: The steps that run something, and so are steps of the run's progress.
RUNS = ("tdd", "exe", "python")


def tdd_module_dir() -> pathlib.Path:
    """The directory holding the ``tdd`` module a python step imports, and
    nothing else: what goes on its PYTHONPATH."""
    return pathlib.Path(str(files("tabsdata_dev.tool.xp").joinpath("scriptlib")))


# ------------------------------------------------------------ selection ----
@dataclass(frozen=True)
class Selection:
    """What the tag flags pick: ``tags`` (None: every step), ``skip``, or
    nothing at all (``--no-actions``)."""

    tags: frozenset[str] | None = None
    skip: frozenset[str] = field(default_factory=frozenset)
    none: bool = False

    def picks(self, tags: frozenset[str]) -> bool:
        if self.none:
            return False
        if self.tags is not None and not tags & self.tags:
            return False
        return not tags & self.skip

    def flags(self) -> list[str]:
        """The flags that make this selection again, for a fan-out child."""
        if self.none:
            return ["--no-actions"]
        out = []
        if self.tags is not None:
            out += ["--tags", ",".join(sorted(self.tags))]
        if self.skip:
            out += ["--skip-tags", ",".join(sorted(self.skip))]
        return out


def _tag_list(value: str | None) -> frozenset[str] | None:
    if value is None:
        return None
    return frozenset(t.strip() for t in value.split(",") if t.strip())


def selection_of(args: argparse.Namespace) -> Selection:
    tags = _tag_list(getattr(args, "tags", None))
    skip = _tag_list(getattr(args, "skip_tags", None)) or frozenset()
    if getattr(args, "no_actions", False):
        if tags is not None or skip:
            state.die("--no-actions runs no action: it takes no --tags or --skip-tags")
        return Selection(none=True)
    return Selection(tags=tags, skip=skip)


def _tags(a: Action, inherited: frozenset[str]) -> frozenset[str]:
    return inherited | frozenset(a.body.tags)


def _picked(a: Action, sel: Selection, inherited: frozenset[str]) -> bool:
    tags = _tags(a, inherited)
    if a.children:
        return any(_picked(c, sel, tags) for c in a.children)
    return sel.picks(tags)


def count(
    entries: list[Action], sel: Selection, inherited: frozenset[str] = frozenset()
) -> int:
    """How many steps of the run's progress the script makes -- the ones that
    run something -- through every loop."""
    total = 0
    for a in entries:
        tags = _tags(a, inherited)
        if a.kind in RUNS:
            total += sel.picks(tags)
        elif a.children:
            total += count(a.children, sel, tags) * (
                a.loop.repeat if a.kind == "loop" else 1
            )
    return total


def labels(
    entries: list[Action],
    sel: Selection,
    where: str = "",
    inherited: frozenset[str] = frozenset(),
) -> Iterator[str]:
    """The label each step of the script is noted with, as `_run_list` builds
    it."""
    for a in entries:
        tags = _tags(a, inherited)
        label = f"{where} > {a.name}" if where else a.name
        if a.kind in RUNS and sel.picks(tags):
            yield label
        elif a.kind == "loop":
            n = a.loop.repeat
            for i in range(1, n + 1):
                yield from labels(
                    a.children, sel, f"{label} {i}/{n}" if n > 1 else label, tags
                )
        elif a.children:
            yield from labels(a.children, sel, label, tags)


# --------------------------------------------------------------- the run ----
def _new_group() -> dict:
    """Popen options that start a step in a process group of its own, so it
    is killed whole."""
    if os.name == "nt":
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def _terminate(p: subprocess.Popen) -> None:
    """SIGTERM a step's process group, then, after a grace, SIGKILL."""
    if p.poll() is not None:
        return
    try:
        if os.name == "nt":
            p.terminate()
        else:
            os.killpg(p.pid, signal.SIGTERM)
        p.wait(KILL_GRACE)
    except subprocess.TimeoutExpired:
        if os.name == "nt":
            p.kill()
        else:
            os.killpg(p.pid, signal.SIGKILL)
    except (ProcessLookupError, PermissionError, OSError):
        pass


class _Run:
    """What every thread of the script shares: the stop flag, the first
    failure (the run's), the steps failed with continue_on_fail, the processes
    running and the timed-out blocks left to run."""

    def __init__(self, inst: Instance, project: str | None, sel: Selection) -> None:
        self.inst = inst
        self.project = project
        self.sel = sel
        self.stop = threading.Event()
        self.first: BaseException | None = None
        self.deferred = 0
        self.abandoned: set[Future] = set()
        # Set once the run is ending: a step it kills then was ended, not failed.
        self.ending = False
        self._procs: set[subprocess.Popen] = set()
        self._lock = threading.Lock()

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            if self.first is None:
                self.first = exc
        self.stop.set()

    def defer(self) -> None:
        with self._lock:
            self.deferred += 1

    def track(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.add(p)

    def untrack(self, p: subprocess.Popen) -> None:
        with self._lock:
            self._procs.discard(p)

    def kill_all(self) -> None:
        with self._lock:
            running = list(self._procs)
        for p in running:
            _terminate(p)

    def pause(self, seconds: float) -> None:
        if not seconds:
            return
        if state.run.dry_run:
            shell.dry_echo(["sleep", f"{seconds:g}"])
            return
        rep().log(f"sleep {seconds:g}s")
        self.stop.wait(seconds)  # a failure elsewhere cuts the pause short

    def spawn(self, body) -> Future:
        """`body` on a thread of its own. A thread, not a bounded pool: an entry
        may wait for another, and a pool full of waiters would never run what
        they wait for."""
        future: Future = Future()

        def target() -> None:
            try:
                body()
            except BaseException as exc:  # noqa: BLE001 -- the run's, via fail()
                self.fail(exc)
                future.set_exception(exc)
            else:
                future.set_result(None)

        threading.Thread(target=target, daemon=True).start()
        return future

    def join(self, futures: list[Future]) -> None:
        for future in futures:
            if future in self.abandoned:
                continue
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 -- recorded by fail()
                self.fail(exc)


class _Scope:
    """One running list -- the script's top, a block's, one pass of a loop:
    the background runs it started, by name, and the scope it sits in."""

    def __init__(self, parent: _Scope | None) -> None:
        self.parent = parent
        self._running: dict[str, list[Future]] = {}
        self._lock = threading.Lock()

    def started(self, name: str, future: Future) -> None:
        with self._lock:
            self._running.setdefault(name, []).append(future)

    def runs_of(self, name: str) -> list[Future]:
        scope: _Scope | None = self
        while scope is not None:
            with scope._lock:
                if name in scope._running:
                    return list(scope._running[name])
            scope = scope.parent
        return []  # it ran blocking, or not at all: nothing to wait for

    def everything(self) -> list[Future]:
        with self._lock:
            return [f for runs in self._running.values() for f in runs]


def _run_list(
    entries: list[Action],
    scope: _Scope,
    run: _Run,
    where: str,
    inherited: frozenset[str],
) -> None:
    for a in entries:
        if run.stop.is_set():
            return
        if not _picked(a, run.sel, inherited):
            continue
        tags = _tags(a, inherited)
        label = f"{where} > {a.name}" if where else a.name
        if a.kind == "sleep":
            run.pause(a.sleep.seconds)
        elif a.kind == "wait":
            names = ", ".join(a.wait.for_)
            rep().log(f"actions {label}: wait for {names}")
            if state.run.dry_run:
                shell.dry_text(f"# {label}: wait for {names}")
            for name in a.wait.for_:
                run.join(scope.runs_of(name))
        elif a.kind == "background":
            if state.run.dry_run:
                # The plan stays one ordered list: where a block starts, marked.
                shell.dry_text(f"# {label}: starts in the background")
                _block(a, scope, run, label, tags)
                shell.dry_text(f"# {label}: ends")
            else:
                rep().log(f"actions {label}: starts in the background")
                scope.started(
                    a.name,
                    run.spawn(
                        lambda a=a, label=label, tags=tags: _block(
                            a, scope, run, label, tags
                        )
                    ),
                )
        elif a.kind == "parallel":
            _parallel(a, scope, run, label, tags)
        elif a.kind == "loop":
            _loop(a, scope, run, label, tags)
        elif a.kind == "timeout":
            _timeout(a, scope, run, label, tags)
        else:
            _step(a, run, label)


def _block(
    a: Action, scope: _Scope, run: _Run, label: str, tags: frozenset[str]
) -> None:
    """A block's actions in a scope of their own, done when all they started is."""
    inner = _Scope(scope)
    try:
        _run_list(a.children, inner, run, label, tags)
    except BaseException as exc:
        run.fail(exc)  # before the join: what still runs must stop
        raise
    finally:
        run.join(inner.everything())


def _parallel(
    a: Action, scope: _Scope, run: _Run, label: str, tags: frozenset[str]
) -> None:
    if state.run.dry_run:
        shell.dry_text(f"# {label}: side by side")
        _block(a, scope, run, label, tags)
        shell.dry_text(f"# {label}: joined")
        return
    inner = _Scope(scope)
    gate = threading.Semaphore(a.parallel.lanes) if a.parallel.lanes else None

    def lane(child: Action) -> None:
        if gate is None:
            _run_list([child], inner, run, label, tags)
            return
        with gate:
            _run_list([child], inner, run, label, tags)

    lanes = [run.spawn(lambda c=c: lane(c)) for c in a.children]
    run.join(lanes)
    run.join(inner.everything())


def _loop(
    a: Action, scope: _Scope, run: _Run, label: str, tags: frozenset[str]
) -> None:
    n = a.loop.repeat
    for i in range(1, n + 1):
        if run.stop.is_set():
            return
        here = f"{label} {i}/{n}" if n > 1 else label
        inner = _Scope(scope)
        try:
            _run_list(a.children, inner, run, here, tags)
        except BaseException as exc:
            run.fail(exc)
            raise
        finally:
            run.join(inner.everything())  # a pass is done when all it started is


def _timeout(
    a: Action, scope: _Scope, run: _Run, label: str, tags: frozenset[str]
) -> None:
    t = a.timeout
    if state.run.dry_run:
        shell.dry_text(f"# {label}: at most {t.time}")
        _block(a, scope, run, label, tags)
        return
    future = run.spawn(lambda: _block(a, scope, run, label, tags))
    done, _ = wait_futures([future], timeout=t.seconds)
    if done:
        run.join([future])
        return
    if t.stop_on_timeout:
        exc = state.XpError(f"timeout {label!r}: its actions ran past {t.time}")
        run.fail(exc)
        run.kill_all()  # the run is over: what the block runs is not waited for
        raise exc
    rep().note(f"{label}: past its {t.time}, left running -- killed when the run ends")
    # Still waitable by name; what the run's end joins it is not.
    run.abandoned.add(future)
    scope.started(a.name, future)


# ----------------------------------------------------------------- steps ----
def script_env(inst: Instance, project: str | None) -> dict:
    """A step's environment: the run's names, and `tdd-exe` first on the PATH
    (`tdd` is a shell function and cannot be exec'd)."""
    tdd_exe = pathlib.Path(proc.tool_argv("tdk")[0]).parent
    return {
        **shell.domain_env(),
        "PATH": os.pathsep.join([str(tdd_exe), os.environ.get("PATH", "")]),
        "XP_WORK_DIR": str(work.work_dir()),
        "XP_PROJECT": project or "",
        "XP_ID": inst.xp_id,
        "XP_SHORT_ID": inst.short_id,
        "XP_SUITE_RUN": inst.name,
        "XP_SUITE_DIR": inst.source_dir,
    }


def _domain_of(options: list[str]) -> str | None:
    for i, o in enumerate(options):
        if o == "--domain" and i + 1 < len(options):
            return options[i + 1]
        if o.startswith("--domain="):
            return o.split("=", 1)[1]
    return None


def argv_of(a: Action, inst: Instance, project: str | None) -> list[str]:
    b = a.body
    if a.kind == "tdd":
        return proc.tool_argv(b.tool, b.command, *work.expand_args(b.options, project))
    params = work.expand_args(b.params, project)
    if a.kind == "exe":
        return [b.program, *params]
    withs = [w for r in b.reqs for w in ("--with", r)]
    script = str(pathlib.Path(inst.source_dir) / b.script)
    return ["uv", "run", "--no-project", *withs, script, *params]


def read_note(lines: list[str]) -> str:
    """The note a python step printed: its last ``xp-note:`` line, or none."""
    notes = [ln[len(NOTE_MARK) :].strip() for ln in lines if ln.startswith(NOTE_MARK)]
    line = notes[-1] if notes else ""
    return line if len(line) <= NOTE_MAX else line[: NOTE_MAX - 3] + "..."


def _step(a: Action, run: _Run, label: str) -> None:
    """Run one tdd, exe or python step as a step of the run, its output into
    run.log line by line as it comes."""
    b, inst = a.body, run.inst
    argv = argv_of(a, inst, run.project)
    if a.kind == "tdd":
        action, path = b.command, _domain_of(argv) or b.tool
    elif a.kind == "exe":
        action, path = "exe", b.program
    else:
        action, path = "python", b.script
    if state.run.dry_run:
        shell.dry_echo(argv)
        rep().step_done(action, path, 0.0, True, label)
        return
    env = script_env(inst, run.project)
    if a.kind == "python":
        env["PYTHONPATH"] = os.pathsep.join(
            p for p in (str(tdd_module_dir()), os.environ.get("PYTHONPATH", "")) if p
        )
    cwd = None if a.kind == "tdd" else inst.source_dir
    t = time.perf_counter()
    rep().log(f"$ {shell.shell_line(argv)}   [{label}]")
    tail: deque[str] = deque(maxlen=TAIL_LINES)
    marked: list[str] = []
    try:
        p = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            **_new_group(),
        )
    except OSError as exc:
        code: int | None = None
        tail.append(str(exc))
    else:
        run.track(p)
        try:
            for raw in p.stdout:  # type: ignore[union-attr]
                rep().log_line(label, raw)
                line = raw.rstrip("\n")
                if line.strip():
                    tail.append(line)
                if line.startswith(NOTE_MARK):
                    marked.append(line)
            code = p.wait()
        finally:
            run.untrack(p)
    seconds = time.perf_counter() - t
    rep().log(f"{label}: exit {code}")
    said = read_note(marked)
    note = "; ".join(filter(None, [label, said]))
    if code == 0:
        rep().step_done(action, path, seconds, True, note)
        return
    why = f"{shell.shell_line(argv)} " + (
        f"exited {code}" if code is not None else "did not start"
    )
    if tail:
        why += ":\n" + "\n".join(tail)
    if run.ending:
        rep().step_done(
            action, path, seconds, False, f"{note}; killed: the run ended", why
        )
        return
    if b.continue_on_fail:
        rep().step_done(action, path, seconds, False, f"{note}; continue_on_fail", why)
        run.defer()
        return
    rep().step_done(action, path, seconds, False, note, why)
    state.die(f"{a.kind} {a.name!r} failed: {why}")


# --------------------------------------------------------------- session ----
class Session:
    """The suite's actions stages, however many: one script, one scope, so a
    background block keeps running through the stages after it and a later
    wait finds it. `finish` -- the suite's end -- waits for everything still
    running but the timed-out blocks left to run, which it kills; `abort`
    stops it all when a stage fails. Either raises the first failure."""

    def __init__(
        self, inst: Instance, project: str | None, sel: Selection | None = None
    ) -> None:
        self._run = _Run(inst, project, sel or Selection())
        self._top = _Scope(None)

    @property
    def deferred(self) -> int:
        """Steps that failed with continue_on_fail: the run fails at its end."""
        return self._run.deferred

    def stage(self, entries: list[Action]) -> None:
        """Run one actions stage; blocking entries before returning. A failure
        in any entry so far is raised here, so the next stage does not start
        on top of it."""
        if self._run.stop.is_set():
            self._raise()
        try:
            _run_list(entries, self._top, self._run, "", frozenset())
        except BaseException as exc:
            self._run.fail(exc)
            self.finish()
        if self._run.stop.is_set():
            self.finish()

    def check(self) -> None:
        """Between stages: a background entry that failed stops the suite."""
        if self._run.stop.is_set():
            self.finish()

    def abort(self, exc: BaseException) -> None:
        self._run.fail(exc)
        self._end()

    def finish(self) -> None:
        self._end()
        self._raise()

    def _end(self) -> None:
        self._run.join(self._top.everything())
        if self._run.abandoned:
            self._run.ending = True
            self._run.stop.set()
            self._run.kill_all()
            # Killed, they end at once: let them say so before the run closes.
            wait_futures(list(self._run.abandoned), timeout=KILL_GRACE + 5)

    def _raise(self) -> None:
        if self._run.first is not None:
            raise self._run.first


def run_script(inst: Instance, project: str | None, sel: Selection) -> int:
    """Every actions stage of the suite as one script, to the end of
    everything it started -- what `run-actions` runs. Returns how many steps
    failed with continue_on_fail; the first other failure is raised once all
    of it has stopped."""
    session = Session(inst, project, sel)
    session.stage(inst.actions)
    session.finish()
    return session.deferred


def cmd_run_actions(args) -> None:
    """Every actions stage of the suite run, in order, as one script -- and
    nothing else: the phase verb a failed run's actions are run again by."""
    from . import domains, lanes, pointers, project
    from .reporter import reporting

    sel = selection_of(args)
    with reporting(
        args,
        "run-actions",
        args.suite_run,
        suite=pointers.suite_of_instance(args.suite_run),
    ):
        members = pointers.instance_group(args.suite_run)
        if members is not None:
            proj = getattr(args, "project", None)
            lanes.dispatch(
                f"run-actions group '{args.suite_run}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "run-actions",
                            "--suite-run",
                            m,
                            *(
                                [
                                    "--project",
                                    f"{proj}_{lanes.lane_of(args.suite_run, m)}",
                                ]
                                if proj
                                else []
                            ),
                            "--secret-env",
                            state.run.secret_env,
                            *sel.flags(),
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="actions",
                base=args.suite_run,
            )
            return
        inst = pointers.load_instance(args.suite_run)
        if not inst.actions:
            rep().note(f"run-actions: suite of '{args.suite_run}' has no actions")
            return
        domains.require_crypto_key()
        proj = getattr(args, "project", None) or project.default_project(args.suite_run)
        rep().plan(count(inst.actions, sel))
        deferred = run_script(inst, proj, sel)
        if deferred:
            state.die(
                f"{deferred} step(s) failed (continue_on_fail let the script run on)"
            )
