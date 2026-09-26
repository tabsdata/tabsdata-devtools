#
# Copyright 2026 Tabsdata Inc.
#
"""Live domains: a suite's ``live`` script, run against its domains while the
project is up -- the data changing under the functions the way a real source's
does, so a stream publisher or a re-triggered publisher has something to see.

The script is a list of named entries (``models.LiveEntry``) of four kinds::

    "live": [
      {"name": "seed", "domain": {"name": "pg", "command": "create-data"}},
      {"name": "churn", "blocking": false, "repeat": 20, "live": [
        {"name": "churn-pause", "sleep_secs": 1},
        {"name": "churn-change", "domain": {"name": "pg", "command": "modify-data",
                                            "options": ["--sets", "2"]}}
      ]},
      {"name": "files", "blocking": false, "domain": {"name": "s3",
        "command": "modify-data", "options": ["--ops", "Insert"]}},
      {"name": "settle", "wait": ["churn", "files"]},
      {"name": "reset", "domain": {"name": "pg", "command": "delete-data"}}
    ]

A domain entry is one `tdd domain` data verb; ``sleep_secs`` pauses; ``wait``
holds until the entries it names have finished; ``repeat`` runs a nested
``live`` script N times. Domain and repeat entries are blocking unless they say
``"blocking": false``: then they start on a thread of their own and the script
goes straight on, side by side. A script -- the whole one, or one pass of a
repeat -- is complete when everything it started has finished, so its end waits
for what is still running and nothing outlives the loop that started it.

A wait names entries before it in its own list or an enclosing one (checked
when the suite is read), so what it names has been started, on this path, by
the time it is reached; each pass of a repeat has its own scope, so a name
means that pass's run. Every call is one step of the run, labelled with the
entries and passes it is under (``churn 7/20 > churn-change``). The first
failure anywhere stops the script: every entry still running stops at its next
step or pause, nothing later starts, and that failure is the run's error.
``create-model``/``create-data`` default ``--model``/``--size`` to what the
suite's domain declares. Under --dry-run the calls print in script order as
the commands they are, the pauses as ``sleep N``, and where an entry goes to the
background, ends or is waited for as ``#`` comment lines.
"""

from __future__ import annotations

import threading
from concurrent.futures import Future

from tabsdata_dev.common.core import proc

from . import domains, lanes, pointers, shell, state
from .models import Instance, LiveDomain, LiveEntry
from .reporter import rep, reporting


def count(entries: list[LiveEntry]) -> int:
    """How many calls the script makes -- its steps, for the [N/M] total."""
    total = 0
    for e in entries:
        if e.domain is not None:
            total += 1
        elif e.live is not None:
            total += e.passes * count(e.live)
    return total


def argv_of(inst: Instance, d: LiveDomain) -> list[str]:
    """`tdd domain <command> --domain <instance>_<name> <options...>`, the
    suite domain's model and size filled in where the entry left them out."""
    extra: list[str] = []
    spec = inst.domain(d.name)
    if d.command == "create-model" and not d.has_option("--model"):
        if not spec.model:
            state.die(
                f"live create-model on '{d.name}': no --model in its options and the suite's domain declares none"
            )
        extra = ["--model", spec.model]
    if d.command == "create-data" and not d.has_option("--size") and spec.model:
        extra = ["--size", str(domains.size_multiplier(spec.data or "xs"))]
    return proc.tool_argv(
        "domain", d.command, "--domain", inst.domain_full(d.name), *d.options, *extra
    )


def _call(argv: list[str], action: str, path: str, where: str) -> None:
    with rep().step(action, path) as step:
        step["note"] = where
        if state.run.dry_run:
            shell.dry_echo(argv)
            return
        r = shell.run_cmd(
            [*argv, "--format", "json"], check=False, env=shell.domain_env()
        )
        if r.returncode != 0:
            final = shell.last_event(r.stdout) or {}
            why = str(final.get("message") or shell.last_err(r)).splitlines()
            state.die(
                f"{shell.shell_line(argv)} exited {r.returncode}"
                + (f": {why[0]}" if why else "")
            )


class _Run:
    """What every thread of one script shares: the stop flag and the first
    failure, which is the run's."""

    def __init__(self) -> None:
        self.stop = threading.Event()
        self.first: BaseException | None = None
        self._lock = threading.Lock()

    def fail(self, exc: BaseException) -> None:
        with self._lock:
            if self.first is None:
                self.first = exc
        self.stop.set()

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
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 -- recorded by fail()
                self.fail(exc)


class _Scope:
    """One running script -- the whole one, or one pass of a repeat: the
    background runs it started, by name, and the scope it sits in."""

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
        return []  # it ran blocking: finished before the wait was reached

    def everything(self) -> list[Future]:
        with self._lock:
            return [f for runs in self._running.values() for f in runs]


def _run_list(
    inst: Instance, entries: list[LiveEntry], scope: _Scope, run: _Run, where: str
) -> None:
    for e in entries:
        if run.stop.is_set():
            return
        label = f"{where} > {e.name}" if where else e.name
        if e.sleep_secs is not None:
            run.pause(e.sleep_secs)
        elif e.wait is not None:
            rep().log(f"live {label}: wait for {', '.join(e.wait)}")
            if state.run.dry_run:
                shell.dry_text(f"# {label}: wait for {', '.join(e.wait)}")
            for name in e.wait:
                run.join(scope.runs_of(name))
        elif e.is_blocking or state.run.dry_run:
            # Under --dry-run the plan stays one ordered list: a background
            # entry prints where it starts, marked.
            if not e.is_blocking:
                shell.dry_text(f"# {label}: starts in the background")
            _run_entry(inst, e, scope, run, label)
            if not e.is_blocking:
                shell.dry_text(f"# {label}: ends")
        else:
            rep().log(f"live {label}: starts in the background")
            scope.started(
                e.name,
                run.spawn(
                    lambda e=e, label=label: _run_entry(inst, e, scope, run, label)
                ),
            )


def _run_entry(
    inst: Instance, e: LiveEntry, scope: _Scope, run: _Run, label: str
) -> None:
    if e.domain is not None:
        d = e.domain
        _call(argv_of(inst, d), d.command, inst.domain_full(d.name), label)
        return
    for i in range(1, e.passes + 1):
        if run.stop.is_set():
            return
        here = f"{label} {i}/{e.passes}" if e.passes > 1 else label
        inner = _Scope(scope)
        try:
            _run_list(inst, e.live or [], inner, run, here)
        except BaseException as exc:
            run.fail(exc)  # before the join: what still runs must stop
            raise
        finally:
            run.join(inner.everything())  # a pass is done when all it started is


def run_script(inst: Instance) -> None:
    """The ``live`` script, to the end of everything it started. The first
    failure anywhere is raised once all of it has stopped."""
    run = _Run()
    top = _Scope(None)
    try:
        _run_list(inst, inst.live, top, run, "")
    except BaseException as exc:
        run.fail(exc)
    finally:
        run.join(top.everything())
    if run.first is not None:
        raise run.first


def has_live(definitions) -> bool:
    """Whether any of these suite definitions carries a live program."""
    from .models import build_instance

    return any(build_instance("_", d).live for d in definitions)


def cmd_live_domains(args) -> None:
    with reporting(
        args,
        "live-domains",
        args.instance,
        suite=pointers.suite_of_instance(args.instance),
    ):
        members = pointers.instance_group(args.instance)
        if members is not None:
            lanes.dispatch(
                f"live-domains group '{args.instance}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "live-domains",
                            "--instance",
                            m,
                            "--secret-env",
                            state.run.secret_env,
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="live",
                base=args.instance,
            )
            return
        inst = pointers.load_instance(args.instance)
        if not inst.live:
            rep().note(f"live-domains: suite of '{args.instance}' has no live program")
            return
        domains.require_crypto_key()
        rep().plan(count(inst.live))
        run_script(inst)
