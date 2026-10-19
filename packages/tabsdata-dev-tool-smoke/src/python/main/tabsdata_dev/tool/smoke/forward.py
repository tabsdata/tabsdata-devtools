#
# Copyright 2026 Tabsdata Inc.
#

"""`kubectl port-forward LOCAL:REMOTE` for a cluster smoke run, SUPERVISED.

The forward is one long-lived stream through the cluster's tunnel, and the
tunnel drops on its own: on AKS the node autoprovisioner replacing the node
that carries the konnectivity agents ended a run's forward mid-suite (`error:
lost connection to pod`), twice in two days, and every stage after it failed
in a second as "not logged in". kubectl does not reconnect, so a supervisor
relaunches it whenever it exits: a drop costs the requests in flight and
nothing after them.

The supervisor is a process of its own, started by `start` and left running:
its pid is kept in the run's STATE file, it writes kubectl's output and its own
straight into the run's log (never into a pipe a caller may be reading), and it
ends when the STOP file appears or the script that started it is gone.
"""

from __future__ import annotations

import dataclasses
import os
import pathlib
import socket
import subprocess
import sys
import time
from collections.abc import Callable

import psutil

from tabsdata_dev.common.core import proc

KUBECTL = "kubectl"
SUPERVISE = "forward-supervise"

PROBE_TIMEOUT = 1.0
#: How long a start waits for LOCAL to answer, and how often it looks.
START_WAIT = 60
START_POLL = 2
#: How long an ensure gives a live supervisor to bring a dropped tunnel back.
ENSURE_GRACE = 20
#: The pause before relaunching a kubectl that died young.
PAUSE = 2
#: How long a stop waits for the supervisor before killing it.
STOP_WAIT = 10
SUPERVISOR_POLL = 0.2


@dataclasses.dataclass(frozen=True)
class Forward:
    kubeconfig: str
    namespace: str
    service: str
    local: int
    remote: int

    def argv(self) -> list[str]:
        return [
            KUBECTL,
            "port-forward",
            "--kubeconfig",
            self.kubeconfig,
            "--namespace",
            self.namespace,
            f"service/{self.service}",
            f"{self.local}:{self.remote}",
        ]

    def options(self) -> list[str]:
        return [
            "--kubeconfig",
            self.kubeconfig,
            "--namespace",
            self.namespace,
            "--service",
            self.service,
            "--local",
            str(self.local),
            "--remote",
            str(self.remote),
        ]


@dataclasses.dataclass(frozen=True)
class Run:
    """Where a run keeps its forward: the supervisor's pid, the file that ends
    it, the log it writes to, and the script it dies with."""

    state: pathlib.Path
    stop: pathlib.Path
    log: pathlib.Path
    parent: int
    steady: float


def answers(port: int) -> bool:
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=PROBE_TIMEOUT):
            return True
    except OSError:
        return False


def _supervisor(state: pathlib.Path) -> psutil.Process | None:
    """The supervisor the state names, if it is still that process."""
    try:
        pid = int(state.read_text().strip())
        process = psutil.Process(pid)
        if process.status() == psutil.STATUS_ZOMBIE:
            return None
        if SUPERVISE not in " ".join(process.cmdline()):
            return None
        return process
    except (OSError, ValueError, psutil.Error):
        return None


def _pid(state: pathlib.Path) -> str:
    try:
        return state.read_text().strip()
    except OSError:
        return "?"


def _sleep_until(seconds: float, ended: Callable[[], bool]) -> None:
    waited = 0.0
    while waited < seconds and not ended():
        time.sleep(SUPERVISOR_POLL)
        waited += SUPERVISOR_POLL


def supervise(forward: Forward, run: Run) -> None:
    """Relaunch kubectl whenever it exits, until the run says stop. A kubectl
    that had been up for STEADY seconds dropped a working tunnel and is
    relaunched at once -- every second of a pause refuses the requests made in
    it; one that died sooner (the service not there yet, the port taken) is
    paused for, so a forward that cannot start does not spin."""

    def ended() -> bool:
        return run.stop.exists() or not psutil.pid_exists(run.parent)

    # its own pid, not its starter's: on Windows `_smoke.exe` is a launcher
    # with this python as its child, and the launcher is not what to stop
    run.state.write_text(f"{os.getpid()}\n")

    with run.log.open("a", encoding="utf-8") as log:

        def say(text: str) -> None:
            log.write(f"{text}\n")
            log.flush()

        while not ended():
            started = time.monotonic()
            child = proc.popen(
                forward.argv(), stdin=subprocess.DEVNULL, stdout=log, stderr=log
            )
            while child.poll() is None and not ended():
                time.sleep(SUPERVISOR_POLL)
            if child.poll() is None:
                child.terminate()
                try:
                    child.wait(timeout=STOP_WAIT)
                except subprocess.TimeoutExpired:
                    child.kill()
                break
            up = int(time.monotonic() - started)
            if up >= run.steady:
                say(
                    f"port-forward: kubectl exited {child.returncode} after {up}s "
                    "(the tunnel dropped?); relaunching now"
                )
                continue
            say(
                f"port-forward: kubectl exited {child.returncode} after {up}s; "
                f"relaunching in {PAUSE}s"
            )
            _sleep_until(PAUSE, ended)


def _engine() -> pathlib.Path:
    """This toolset's own `_smoke`, which runs the supervisor."""
    return proc.venv_exe(pathlib.Path(sys.prefix), "_smoke")


def start(forward: Forward, run: Run, say: Callable[[str], None]) -> bool:
    """Start the forward under a new supervisor and return once LOCAL answers
    (False after START_WAIT). One at a time: a running forward is stopped
    first. A LOCAL that something already answers on -- another run, a forward
    a --keep run left, a local tdkserver -- is refused before kubectl runs:
    kubectl would fail to bind while the probe answered, and the run would log
    in to whatever is there."""
    stop(forward, run, say)
    if answers(forward.local):
        say(
            f"127.0.0.1:{forward.local} is already taken; "
            "pick another with --kube-port-forward"
        )
        return False
    run.stop.unlink(missing_ok=True)
    with run.log.open("a", encoding="utf-8") as log:
        supervisor = proc.popen(
            [
                str(_engine()),
                SUPERVISE,
                *forward.options(),
                "--state",
                str(run.state),
                "--stop",
                str(run.stop),
                "--log",
                str(run.log),
                "--parent",
                str(run.parent),
                "--steady",
                f"{run.steady:g}",
            ],
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=log,
        )
    waited = 0
    while not answers(forward.local):
        if supervisor.poll() is not None:
            say("port-forward supervisor exited (see the log above)")
            run.state.unlink(missing_ok=True)
            return False
        if waited >= START_WAIT:
            say(
                f"port {forward.local} not answering after {waited}s "
                "(kubectl's exits are in the log above)"
            )
            stop(forward, run, say)
            if supervisor.poll() is None:
                supervisor.kill()
            return False
        time.sleep(START_POLL)
        waited += START_POLL
    say(
        f"port-forward up: 127.0.0.1:{forward.local} -> service/{forward.service}:"
        f"{forward.remote} in {forward.namespace} (supervisor pid {_pid(run.state)})"
    )
    return True


def ensure(forward: Forward, run: Run, say: Callable[[str], None]) -> bool:
    """Before a stage that needs the server: LOCAL answers, or the forward is
    started afresh. A tunnel drop is recovered by the supervisor within
    seconds, so a live one first gets ENSURE_GRACE; a supervisor that is gone,
    or a port still dead after that, gets a fresh start."""
    waited = 0
    while (supervisor := _supervisor(run.state)) is not None:
        if answers(forward.local):
            if waited > 0:
                say(
                    f"port-forward back after {waited}s "
                    "(the supervisor relaunched kubectl)"
                )
            say(
                f"port-forward up: 127.0.0.1:{forward.local} "
                f"(supervisor pid {supervisor.pid})"
            )
            return True
        if waited >= ENSURE_GRACE:
            say(
                f"port {forward.local} not answering after {waited}s with the "
                "supervisor alive; starting the forward afresh"
            )
            break
        time.sleep(START_POLL)
        waited += START_POLL
    if _supervisor(run.state) is None:
        say("port-forward supervisor is gone; starting the forward afresh")
    return start(forward, run, say)


def stop(forward: Forward, run: Run, say: Callable[[str], None]) -> None:
    """End the forward, if one is up; a no-op otherwise, so it is safe
    anywhere. The supervisor ends its kubectl on the stop file; a kubectl it
    did not get to end (the supervisor killed outright) is swept by its
    command line, which is this run's alone."""
    try:
        pid = run.state.read_text().strip()
    except OSError:
        return
    supervisor = _supervisor(run.state)
    if supervisor is not None:
        run.stop.touch()
        try:
            supervisor.wait(timeout=STOP_WAIT)
        except psutil.TimeoutExpired:
            supervisor.kill()
        except psutil.Error:
            pass
    own = " ".join(forward.argv()[1:])
    for process in psutil.process_iter():
        try:
            if own in " ".join(process.cmdline()):
                process.kill()
        except psutil.Error:
            pass
    run.state.unlink(missing_ok=True)
    run.stop.unlink(missing_ok=True)
    say(f"port-forward stopped (supervisor pid {pid})")
