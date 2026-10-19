#
# Copyright 2026 Tabsdata Inc.
#

"""The processes of a local (kminus) tabsdata instance, found BY NAME.

Every one of them -- the km supervisor, the servers, the workers it forks --
carries the instance folder on its command line, `instances/NAME/` (with
backslashes on Windows, read as slashes here). That is how a previous run's
leftovers are recognised without a pid file to trust.
"""

from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import time
from collections.abc import Callable

import psutil

from tabsdata_dev.common.core import proc

TDKSERVER = "tdkserver"

#: How long the processes of a stopped instance are waited out before they are
#: killed, and how often they are looked at meanwhile.
STOP_WAIT = 90
STOP_POLL = 3


def instances_folder() -> pathlib.Path:
    return pathlib.Path.home() / ".tabsdata" / "instances"


def instance_folder(name: str) -> pathlib.Path:
    return instances_folder() / name


def _command_line(process: psutil.Process) -> str:
    try:
        return " ".join(process.cmdline()).replace("\\", "/")
    except (psutil.Error, OSError):
        return ""


def _lineage() -> set[int]:
    # this process and every one above it: a shell that called us may carry
    # the folder in its own command line, and must never be ended by its helper
    own = psutil.Process()
    try:
        return {own.pid, *(p.pid for p in own.parents())}
    except psutil.Error:
        return {own.pid}


def processes(name: str) -> list[psutil.Process]:
    marker = f"instances/{name}/"
    lineage = _lineage()
    return [
        p
        for p in psutil.process_iter()
        if p.pid not in lineage and marker in _command_line(p)
    ]


def pids(name: str) -> list[int]:
    return sorted(p.pid for p in processes(name))


def _tdkserver_candidates(tdd_dir: pathlib.Path) -> list[pathlib.Path]:
    managed = tdd_dir / "managed-venvs"
    found = sorted(
        proc.venv_exe(venv, TDKSERVER) for venv in managed.glob("*/*") if venv.is_dir()
    )
    on_path = shutil.which(TDKSERVER)
    return [*found, *([pathlib.Path(on_path)] if on_path else [])]


def previous_tdkserver(tdd_dir: pathlib.Path) -> pathlib.Path | None:
    """A tdkserver able to stop an instance a previous run left behind: one in
    a managed venv under the tdd dir, else one on PATH that actually runs (a
    pyenv shim may not be wired here)."""
    for candidate in _tdkserver_candidates(tdd_dir):
        if not candidate.is_file():
            continue
        try:
            done = proc.run(
                [str(candidate), "--accept-terms", "y", "--version"],
                capture_output=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            continue
        if done.returncode == 0:
            return candidate
    return None


def _end(found: list[psutil.Process], kill: bool) -> None:
    for process in found:
        try:
            if kill:
                process.kill()
            else:
                process.terminate()
        except psutil.Error:
            pass


def stop(
    name: str,
    tdd_dir: pathlib.Path,
    options: list[str],
    say: Callable[[str], None],
    wait: int = STOP_WAIT,
    poll: float = STOP_POLL,
) -> bool:
    """End the km processes of an instance a previous run left running, and
    WAIT until every one is gone: stop it properly first (tdkserver stop), then
    end the processes still holding the folder, then kill them.

    The wait matters: a km still winding down after a TERM escalates to a kill
    on the pids it tracked ~50s later -- and by then a new instance in the same
    folder has REUSED those pid files, so the new cluster is what gets killed
    (seen: control-plane "process exited (signal 9)" 44s into quickstart)."""
    found = processes(name)
    if not found:
        say(f"no km processes of instance {name} running")
        return True
    say(
        f"instance {name} still running ({len(found)} processes): "
        f"{' '.join(str(p.pid) for p in found)}"
    )
    previous = previous_tdkserver(tdd_dir)
    if previous:
        say(f"$ {previous} stop --instance {name} {' '.join(options)}   (best effort)")
        try:
            # its output belongs in the run's log, and stdout carries the answer
            proc.run(
                [str(previous), "stop", "--instance", name, *options],
                stdout=sys.stderr,
            )
        except (OSError, subprocess.SubprocessError) as error:
            say(f"tdkserver stop failed: {error}")
    if processes(name):
        say(f"ending the processes still holding instances/{name}/")
        _end(processes(name), kill=False)
    waited = 0
    while processes(name) and waited < wait:
        time.sleep(poll)
        waited += poll
    if processes(name):
        say(f"killing the processes still there after {waited:g}s")
        _end(processes(name), kill=True)
        time.sleep(poll)
    left = pids(name)
    if left:
        say(
            f"instance {name} still has processes after {waited:g}s: "
            f"{' '.join(map(str, left))}"
        )
        return False
    say(f"instance {name} gone after {waited:g}s")
    return True


def gone(name: str, say: Callable[[str], None]) -> bool:
    """No km process of the instance left and no instance folder: what a
    trash or a delete must leave."""
    ok = True
    left = pids(name)
    if left:
        say(f"instance {name} still has processes: {' '.join(map(str, left))}")
        ok = False
    folder = instance_folder(name)
    if folder.exists():
        say(f"instance folder still exists: {folder}")
        ok = False
    if ok:
        say(f"instance {name} is gone: no processes, no folder")
    return ok
