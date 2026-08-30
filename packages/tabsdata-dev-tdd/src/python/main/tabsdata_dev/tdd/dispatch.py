#
# Copyright 2026 Tabsdata Inc.
#

"""Executing a tool inside its own toolset environment. Standard library only."""

from __future__ import annotations

import os
import pathlib

from . import catalog as catalog_mod
from . import paths
from . import render
from . import reqs

HELP_FLAGS = ("-h", "--help")


def dispatch(
    dir_: pathlib.Path, tool: str, argv: list[str], out: render.Renderer
) -> int:
    catalog = catalog_mod.installed(dir_)
    entry = catalog["tools"].get(tool)
    if entry is None:
        known = ", ".join(sorted(catalog["tools"])) or "none"
        return out.error(
            f"unknown tool {tool!r}; known: {known}", known=sorted(catalog["tools"])
        )

    if catalog_mod.is_stale(dir_):
        out.warn(
            f"{dir_} predates the current tool set; run `tdd-install --dir {dir_}`"
        )

    # Every declared external binary must be there BEFORE the tool runs -- the
    # same refusal tdd-fn gives a shell command -- so a missing prerequisite is
    # one clear error up front rather than a failure deep inside the tool.
    # Help is the exception: reading what a tool does must never depend on
    # what the machine has installed.
    wants_help = any(a in HELP_FLAGS for a in argv)
    gone = reqs.missing_details(entry.get("reqs", []))
    if gone and not wants_help:
        return out.error(
            _missing_message(tool, gone),
            missing=[b for b, _ in gone],
            why={b: note for b, note in gone if note},
        )

    bin_dir = paths.venvs_dir(dir_) / entry["toolset"] / "bin"
    exe = bin_dir / tool
    if not exe.is_file():
        return out.error(
            f"{tool} is missing from {bin_dir}; run `tdd-install --dir {dir_}`"
        )

    # The toolset's own bin/ goes first so a tool shelling out finds its own
    # pinned binaries; TDD_DIR/TDD_TOOL let it reach siblings and its own
    # catalog entry.
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["TDD_DIR"] = str(dir_)
    env["TDD_TOOL"] = tool

    out.debug(f"exec {exe} {' '.join(argv)}", toolset=entry["toolset"], exe=str(exe))
    os.execve(str(exe), [str(exe), *argv], env)
    return 1  # unreachable; execve does not return


def _missing_message(tool: str, gone: list[tuple[str, str]]) -> str:
    """One line per binary, aligned, the reason beside it -- a wall of
    parentheses is not a list."""
    n = len(gone)
    head = f"{tool} needs {n} required binar{'y that is' if n == 1 else 'ies that are'} not on PATH:"
    width = max(len(b) for b, _ in gone)
    rows = [f"  {b:<{width}}  {note or 'not found'}" for b, note in gone]
    return "\n".join(
        [
            head,
            *rows,
            f"install {'it' if n == 1 else 'them'}; `tdd --reqs {tool}` lists every requirement",
        ]
    )
