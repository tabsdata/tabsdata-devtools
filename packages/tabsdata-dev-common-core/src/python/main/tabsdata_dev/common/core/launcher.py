#
# Copyright 2026 Tabsdata Inc.
#

"""A tool that is a launcher: `tdd <cmd> ARGS` runs `<cmd> ARGS` inside the
venv last activated (common.core.managedvenv.select) and hands its output and
status straight back.

The tabsdata CLIs -- tdk, tdkserver, km -- are installed per project into a
venv the user activates, managed by `tdd venv` or not, never into a toolset,
so a tool for them cannot import or pin anything -- it can only find the venv
and run the real program there. Which venv that is, and why, is the first
thing it says: two venvs with two tabsdata versions is the usual reason a
command behaves unexpectedly. A launcher has no options of its own: every argument, `--help`,
`--format` and `--version` included, belongs to the program, which is the one
deliberate exception to docs/command-cli-guidelines.md. Only what happens
before the program runs -- no venv, or the program missing from it -- is ours,
and is reported as one error event the guidelines' way.

`run_program` is the same contract for a program that is not tabsdata's --
parquet-tools, jq -- found where it is installed once for everyone: pinned by
the tool's own toolset, or on the machine and declared in bin-reqs.txt. No
venv is looked for, so nothing is said before the program runs.
"""

from __future__ import annotations

import argparse
import os
import pathlib
import shutil
import sys

from . import cli, datadir, managedvenv, proc, render
from .errors import ToolError


def run(cmd: str, description: str, argv: list[str] | None = None) -> int:
    args_ = list(sys.argv[1:] if argv is None else argv)

    def body(_: argparse.Namespace, out: render.Renderer) -> int:
        try:
            venv = managedvenv.select()
        except ToolError as exc:
            return out.error(str(exc))
        assert venv is not None
        if _is_tdds_own(venv.path):
            # A toolset venv activated by hand: its `cmd` is this launcher.
            return out.error(
                f"{venv.path} is one of tdd's own toolset venvs, not a project venv; "
                f"deactivate it and activate the venv that has {cmd}"
            )
        # Without this, a manager that cannot find the program falls back to
        # PATH -- where the toolset's bin/ comes first and holds this very
        # launcher under the same name.
        if managedvenv.program(venv.path, cmd) is None:
            hint = (
                f"tdd venv activate --name {venv.name} && pip install ..."
                if venv.name
                else "pip install ... in it"
            )
            return out.error(
                f"{cmd} is not installed in {venv.describe()}; install it there "
                f"first (e.g. {hint})"
            )
        out.info(
            f"{cmd}: {venv.describe()} -- {venv.why}",
            venv=venv.name,
            venv_path=str(venv.path),
            venv_manager=venv.manager,
            venv_reason=venv.why,
        )
        launch, extra = managedvenv.launch_in(venv, cmd, args_)
        try:
            done = proc.run(launch, env={**os.environ, **extra})
        except KeyboardInterrupt:
            # Ctrl-C is how a server is stopped; a log file for it is noise.
            out.warn(f"{cmd} interrupted")
            return 1
        if done.returncode != 0:
            return out.error(
                f"{cmd} exited with status {done.returncode}", status=done.returncode
            )
        return 0

    # The parser sees no arguments: they are all the program's.
    return cli.run(cmd, description, body, argv=[])


def run_program(
    cmd: str,
    program: str,
    description: str,
    *,
    pinned: bool,
    argv: list[str] | None = None,
) -> int:
    """`tdd <cmd> ARGS` runs `<program> ARGS` and hands its output and status
    straight back. `pinned`: the tool's toolset provides the program, so it is
    looked for in this venv's scripts dir only; otherwise it is the machine's,
    looked for on PATH with that dir left out -- it is where the launcher's
    own entry point sits, and a program called like its launcher (`jq`) would
    find the launcher and run it forever."""
    args_ = list(sys.argv[1:] if argv is None else argv)

    def body(_: argparse.Namespace, out: render.Renderer) -> int:
        exe = _find(program, pinned=pinned)
        if exe is None:
            where = "this toolset" if pinned else "PATH"
            return out.error(f"{program} is not installed: not found on {where}")
        try:
            done = proc.run([exe, *args_])
        except KeyboardInterrupt:
            out.warn(f"{program} interrupted")
            return 1
        if done.returncode != 0:
            return out.error(
                f"{program} exited with status {done.returncode}",
                status=done.returncode,
            )
        return 0

    return cli.run(cmd, description, body, argv=[])


def _find(program: str, *, pinned: bool) -> str | None:
    # The interpreter's own dir is the venv's scripts dir: bin/, or Scripts\
    # on Windows, where which() also supplies the .exe.
    own = pathlib.Path(sys.executable).parent
    if pinned:
        return shutil.which(program, path=str(own))
    dirs = [
        d
        for d in os.environ.get("PATH", "").split(os.pathsep)
        if d and not _same_dir(pathlib.Path(d), own)
    ]
    return shutil.which(program, path=os.pathsep.join(dirs))


def _same_dir(a: pathlib.Path, b: pathlib.Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return False


def _is_tdds_own(path: pathlib.Path) -> bool:
    try:
        path.resolve().relative_to((datadir.tdd_dir() / "tdd-venvs").resolve())
    except (ValueError, OSError):
        return False
    return True
