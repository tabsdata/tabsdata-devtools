#
# Copyright 2026 Tabsdata Inc.
#
"""Execute stages: a suite's check scripts, run in order, one step each.

A script is ``py_script`` in the suite dir, run by ``tdd _xp-execute`` -- a
bare venv of its own, built by tdd-install, whose one gift is the ``tdd``
module (``from tdd import tdd``) -- from the suite dir, with its ``params``
(tokens expanded, see ``work``) as argv. It passes by exiting 0. Its output
goes to run.log; a failure's last lines are the step's error.

An entry with ``requirements`` runs in a one-off venv instead: made by ``tdd
_venv create --type uv`` as ``tdd-xp-execute-<run>-<entry>``, filled with
``uv pip install``, handed to ``_xp-execute`` in ``_TDD_XP_EXECUTE_VENV``, and
deleted after the step whether the script passed or not. The prefix finds what
a killed run left behind (``tdd venv list``).

It is handed what it needs to reach the run: ``XP_WORK_DIR``, ``XP_PROJECT``,
``XP_ID``, ``XP_SHORT_ID``, ``XP_SUITE_RUN`` and ``XP_SUITE_DIR`` in its environment, and ``tdd-exe`` on its
PATH (``tdd`` is a shell function and cannot be exec'd).

A line the script prints starting ``xp-note:`` (``tdd.note()`` prints one) is
its step's note, the progress line's free column -- a measured figure, say,
which a pass or fail alone does not carry; the last one wins. It says nothing
about the outcome; the exit code still does.

A failed script stops the run, unless it says ``continue_on_fail``: then the
failure is reported, the stages after it run, and the run fails at its end --
a check that fails is never a green run.
"""

from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import time

from tabsdata_dev.common.core import managedvenv, proc

from . import shell, state, work
from .models import Execute, Instance
from .reporter import RUN_TS, rep

#: How many of a failed script's last output lines make its step error.
TAIL_LINES = 20
#: Every one-off venv's name starts so: what a clean-up after a killed run finds.
VENV_PREFIX = "tdd-xp-execute-"
VENV_PYTHON = "3.12.13"
VENV_ENV = "_TDD_XP_EXECUTE_VENV"
#: A stdout line so marked is the step's note; `tdd.note()` prints one.
NOTE_MARK = "xp-note:"
#: A note is one column of a progress line, not a report: longer is cut.
NOTE_MAX = 160


def read_note(stdout: str) -> str:
    """The note a script printed: its last ``xp-note:`` line, or none."""
    notes = [
        ln[len(NOTE_MARK) :].strip()
        for ln in stdout.splitlines()
        if ln.startswith(NOTE_MARK)
    ]
    line = notes[-1] if notes else ""
    return line if len(line) <= NOTE_MAX else line[: NOTE_MAX - 3] + "..."


def script_env(inst: Instance, project: str | None) -> dict:
    tdd_exe = pathlib.Path(proc.tool_argv("tdk")[0]).parent
    return {
        **os.environ,
        "PATH": os.pathsep.join([str(tdd_exe), os.environ.get("PATH", "")]),
        "XP_WORK_DIR": str(work.work_dir()),
        "XP_PROJECT": project or "",
        "XP_ID": inst.xp_id,
        "XP_SHORT_ID": inst.short_id,
        "XP_SUITE_RUN": inst.name,
        "XP_SUITE_DIR": inst.source_dir,
    }


def venv_name(inst: Instance, e: Execute) -> str:
    """The one-off venv of one entry in one run: the prefix, the run's
    timestamp and pid, the entry -- legal as a managed venv's name."""
    raw = f"{VENV_PREFIX}{RUN_TS}-{os.getpid()}-{inst.name}-{e.name}"
    return re.sub(r"[^A-Za-z0-9._-]", "_", raw)


def _run(argv: list[str], what: str, **kw) -> subprocess.CompletedProcess:
    done = subprocess.run(
        argv, capture_output=True, text=True, encoding="utf-8", errors="replace", **kw
    )
    rep().log(
        f"$ {shell.shell_line(argv)} -> exit {done.returncode}",
        (done.stdout or "") + (done.stderr or ""),
    )
    if done.returncode != 0:
        tail = "\n".join(
            ((done.stdout or "") + (done.stderr or ""))
            .rstrip()
            .splitlines()[-TAIL_LINES:]
        )
        raise state.XpError(f"{what} failed: {tail}")
    return done


def one_off_venv(inst: Instance, e: Execute) -> tuple[str, pathlib.Path]:
    """Make the entry's venv and install its requirements; (name, path)."""
    name = venv_name(inst, e)
    done = _run(
        proc.tool_argv(
            "_venv",
            "create",
            "--name",
            name,
            "--type",
            "uv",
            "--python",
            VENV_PYTHON,
            "--format",
            "json",
        ),
        f"one-off venv {name}",
    )
    event = json.loads(
        [ln for ln in done.stdout.splitlines() if ln.startswith("{")][-1]
    )
    prefix = pathlib.Path(event["path"])
    python = next(
        (
            managedvenv.bin_dir(prefix) / leaf
            for leaf in ("python", "python3", "python.exe")
            if (managedvenv.bin_dir(prefix) / leaf).is_file()
        ),
        None,
    )
    if python is None:
        raise state.XpError(f"one-off venv {name} has no python ({prefix})")
    _run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(python),
            *(r.spec for r in e.requirements),
        ],
        f"installing {', '.join(r.spec for r in e.requirements)} into {name}",
    )
    return name, prefix


def delete_venv(name: str) -> None:
    """Best effort: a venv that will not go is said, not fatal -- its name is
    what `tdd venv list` shows to clean up by hand."""
    done = subprocess.run(
        proc.tool_argv("_venv", "delete", "--name", name, "--format", "json"),
        capture_output=True,
        text=True,
    )
    rep().log(
        f"$ tdd _venv delete --name {name} -> exit {done.returncode}",
        done.stdout + done.stderr,
    )
    if done.returncode != 0:
        rep().note(
            f"one-off venv {name} was not deleted; `tdd venv delete --name {name}` does it"
        )


def run_scripts(inst: Instance, project: str | None, entries: list[Execute]) -> int:
    """Run one execute stage. Returns how many scripts failed with
    ``continue_on_fail`` -- the caller fails the run for them once it ends;
    a script without it that fails raises here."""
    rep().plan(len(entries))
    deferred = 0
    for e in entries:
        argv = proc.tool_argv(
            "_xp-execute",
            str(pathlib.Path(inst.source_dir) / e.py_script),
            *(work.expand(p, project) for p in e.params),
        )
        if state.run.dry_run:
            with rep().step("execute", e.name):
                if e.requirements:
                    shell.dry_echo(
                        proc.tool_argv(
                            "_venv",
                            "create",
                            "--name",
                            venv_name(inst, e),
                            "--type",
                            "uv",
                        )
                    )
                    shell.dry_echo(
                        ["uv", "pip", "install", *(r.spec for r in e.requirements)]
                    )
                shell.dry_echo(argv)
            continue
        t = time.perf_counter()
        env = script_env(inst, project)
        venv = None
        try:
            if e.requirements:
                venv, prefix = one_off_venv(inst, e)
                env[VENV_ENV] = str(prefix)
            r = subprocess.run(
                argv,
                cwd=inst.source_dir,
                env=env,
                stdin=subprocess.DEVNULL,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except state.XpError as exc:
            rep().step_done(
                "execute", e.name, time.perf_counter() - t, False, "", str(exc)
            )
            raise
        finally:
            if venv is not None:
                delete_venv(venv)
        seconds = time.perf_counter() - t
        output = (r.stdout or "") + (r.stderr or "")
        rep().log(f"$ {shell.shell_line(argv)} -> exit {r.returncode}", output)
        note = read_note(r.stdout or "")
        if r.returncode == 0:
            rep().step_done("execute", e.name, seconds, True, note)
            continue
        tail = "\n".join(output.rstrip().splitlines()[-TAIL_LINES:])
        why = f"{e.py_script} exited {r.returncode}" + (f":\n{tail}" if tail else "")
        if e.continue_on_fail:
            said = "; ".join(filter(None, ["continue_on_fail", note]))
            rep().step_done("execute", e.name, seconds, False, said, why)
            deferred += 1
            continue
        rep().step_done("execute", e.name, seconds, False, note, why)
        state.die(f"execute {e.name!r} failed: {why}")
    return deferred
