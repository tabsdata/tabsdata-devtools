#
# Copyright 2026 Tabsdata Inc.
#
"""Execute stages: a suite's check scripts, run in order, one step each.

A script is ``py_script`` in the suite dir, run with xp's own python -- the
toolset xp ships in, so what xp depends on (``parquet-tools``) is there -- from
the suite dir, with its ``params`` (tokens expanded, see ``work``) as argv. It
passes by exiting 0. Its output goes to run.log; a failure's last lines are the
step's error.

It is handed what it needs to reach the run: ``XP_WORK_DIR``, ``XP_PROJECT``,
``XP_INSTANCE`` and ``XP_SUITE_DIR`` in its environment, and a PATH that starts
with xp's venv (``parquet-tools``) and the dispatcher's (``tdd-exe``; ``tdd`` is
a shell function and cannot be exec'd, so a script calls ``tdd-exe tdk ...``).

A failed script stops the run, unless it says ``continue_on_fail``: then the
failure is reported, the stages after it run, and the run fails at its end --
a check that fails is never a green run.
"""

from __future__ import annotations

import os
import pathlib
import subprocess
import sys
import time

from tabsdata_dev.common.core import proc

from . import shell, state, work
from .models import Execute, Instance
from .reporter import rep

#: How many of a failed script's last output lines make its step error.
TAIL_LINES = 20


def script_env(inst: Instance, project: str | None) -> dict:
    tdd_exe = pathlib.Path(proc.tool_argv("tdk")[0]).parent
    here = pathlib.Path(sys.executable).parent
    return {
        **os.environ,
        "PATH": os.pathsep.join([str(here), str(tdd_exe), os.environ.get("PATH", "")]),
        "XP_WORK_DIR": str(work.work_dir()),
        "XP_PROJECT": project or "",
        "XP_INSTANCE": inst.name,
        "XP_SUITE_DIR": inst.source_dir,
    }


def run_scripts(inst: Instance, project: str | None, entries: list[Execute]) -> int:
    """Run one execute stage. Returns how many scripts failed with
    ``continue_on_fail`` -- the caller fails the run for them once it ends;
    a script without it that fails raises here."""
    rep().plan(len(entries))
    deferred = 0
    for e in entries:
        argv = [
            sys.executable,
            str(pathlib.Path(inst.source_dir) / e.py_script),
            *(work.expand(p, project) for p in e.params),
        ]
        if state.run.dry_run:
            with rep().step("execute", e.name):
                shell.dry_echo(argv)
            continue
        t = time.perf_counter()
        r = subprocess.run(
            argv,
            cwd=inst.source_dir,
            env=script_env(inst, project),
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        seconds = time.perf_counter() - t
        output = (r.stdout or "") + (r.stderr or "")
        rep().log(f"$ {shell.shell_line(argv)} -> exit {r.returncode}", output)
        if r.returncode == 0:
            rep().step_done("execute", e.name, seconds, True)
            continue
        tail = "\n".join(output.rstrip().splitlines()[-TAIL_LINES:])
        why = f"{e.py_script} exited {r.returncode}" + (f":\n{tail}" if tail else "")
        if e.continue_on_fail:
            rep().step_done(
                "execute", e.name, seconds, False, "continuing (continue_on_fail)", why
            )
            deferred += 1
            continue
        rep().step_done("execute", e.name, seconds, False, "", why)
        state.die(f"execute {e.name!r} failed: {why}")
    return deferred
