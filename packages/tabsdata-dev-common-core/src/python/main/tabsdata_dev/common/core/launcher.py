#
# Copyright 2026 Tabsdata Inc.
#

"""A tool that is a launcher: `tdd <cmd> ARGS` runs `<cmd> ARGS` inside the
active managed venv (common.core.managedvenv) and hands its output and status
straight back.

The two tabsdata CLIs, tdk and tdkserver, are installed per project into a venv
the user manages with `tdd venv`, not into a toolset, so a tool for them cannot
import or pin anything -- it can only find the venv and run the real program
there. A launcher has no options of its own: every argument, `--help`,
`--format` and `--version` included, belongs to the program, which is the one
deliberate exception to docs/command-cli-guidelines.md. Only what happens
before the program runs -- no venv, or the program missing from it -- is ours,
and is reported as one error event the guidelines' way.
"""

from __future__ import annotations

import argparse
import os
import sys

from . import cli, managedvenv, proc, render
from .errors import ToolError


def run(cmd: str, description: str, argv: list[str] | None = None) -> int:
    args_ = list(sys.argv[1:] if argv is None else argv)

    def body(_: argparse.Namespace, out: render.Renderer) -> int:
        try:
            name = managedvenv.active()
            manager, path = managedvenv.resolve(name)
        except ToolError as exc:
            return out.error(str(exc))
        # Without this, a manager that cannot find the program falls back to
        # PATH -- where the toolset's bin/ comes first and holds this very
        # launcher under the same name.
        if not (path / "bin" / cmd).exists():
            return out.error(
                f"{cmd} is not installed in managed venv {name} ({path}); install it "
                f"there first (e.g. tdd venv activate --name {name} && pip install ...)"
            )
        launch, extra = managedvenv.launch(manager, path, cmd, args_)
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
