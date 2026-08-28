#
# Copyright 2026 Tabsdata Inc.
#

"""Executing a tool inside its own toolset environment. Standard library only."""

from __future__ import annotations

import os
import pathlib
import sys

from . import catalog as catalog_mod
from . import paths


def dispatch(dir_: pathlib.Path, tool: str, argv: list[str]) -> int:
    catalog = catalog_mod.installed(dir_)
    entry = catalog["tools"].get(tool)
    if entry is None:
        known = ", ".join(sorted(catalog["tools"])) or "none"
        print(f"tdd: unknown tool {tool!r}; known: {known}", file=sys.stderr)
        return 2

    if catalog_mod.is_stale(dir_):
        print(
            f"tdd: warning: {dir_} predates the current tool set; "
            f"run `tdd-install --dir {dir_}`",
            file=sys.stderr,
        )

    bin_dir = paths.venvs_dir(dir_) / entry["toolset"] / "bin"
    exe = bin_dir / tool
    if not exe.is_file():
        print(
            f"tdd: {tool} is missing from {bin_dir}; run `tdd-install --dir {dir_}`",
            file=sys.stderr,
        )
        return 2

    # The toolset's own bin/ goes first so a tool shelling out finds its own
    # pinned binaries; TDD_DIR/TDD_TOOL let it reach siblings and its own
    # catalog entry.
    env = dict(os.environ)
    env["PATH"] = str(bin_dir) + os.pathsep + env.get("PATH", "")
    env["TDD_DIR"] = str(dir_)
    env["TDD_TOOL"] = tool

    os.execve(str(exe), [str(exe), *argv], env)
