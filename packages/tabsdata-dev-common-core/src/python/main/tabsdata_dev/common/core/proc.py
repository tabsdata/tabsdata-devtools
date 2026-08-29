#
# Copyright 2026 Tabsdata Inc.
#

"""Process launching -- the single choke point for shelling out.

Every external binary a tool invokes must be declared in that tool's
bin-reqs.txt. Rather than trusting the file to stay current, this module
enforces it: an undeclared binary raises instead of working on the
author's machine and failing on someone else's.
"""

from __future__ import annotations

import functools
import json
import os
import pathlib
import subprocess


class UndeclaredRequirement(RuntimeError):
    pass


@functools.lru_cache(maxsize=1)
def _declared() -> frozenset[str]:
    """Binaries declared by the tool we are running inside.

    Enforcement is skipped when TDD_DIR/TDD_TOOL are absent, so tools
    stay importable under a bare pytest run.
    """
    dir_ = os.environ.get("TDD_DIR")
    tool = os.environ.get("TDD_TOOL")
    if not dir_ or not tool:
        return frozenset()
    catalog = pathlib.Path(dir_) / "catalog.json"
    if not catalog.is_file():
        return frozenset()
    entry = json.loads(catalog.read_text())["tools"].get(tool, {})
    return frozenset(entry.get("reqs", []))


@functools.lru_cache(maxsize=1)
def _toolset_bin() -> pathlib.Path | None:
    """This tool's own toolset bin/, which tdd puts first on PATH."""
    dir_ = os.environ.get("TDD_DIR")
    tool = os.environ.get("TDD_TOOL")
    if not dir_ or not tool:
        return None
    catalog = pathlib.Path(dir_) / "catalog.json"
    if not catalog.is_file():
        return None
    toolset = json.loads(catalog.read_text())["tools"].get(tool, {}).get("toolset")
    return pathlib.Path(dir_) / "tdd-venvs" / toolset / "bin" if toolset else None


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a binary, refusing anything neither pinned nor declared.

    A binary is legitimate one of two ways: this toolset provides it
    (a deps-* pin, so it sits in the toolset's bin/), or it is external
    and named in bin-reqs.txt. Anything else is an undeclared
    dependency on whatever happens to be installed.
    """
    binary = pathlib.Path(argv[0]).name
    if os.environ.get("TDD_TOOL"):
        bin_dir = _toolset_bin()
        pinned = bool(bin_dir and (bin_dir / binary).exists())
        if not pinned and binary not in _declared():
            tool = os.environ["TDD_TOOL"]
            raise UndeclaredRequirement(
                f"{binary!r} is neither pinned by this toolset nor "
                f"declared in tabsdata-dev-tool-{tool}/bin-reqs.txt"
            )
    return subprocess.run(argv, **kwargs)


def tool_argv(name: str, *args: str) -> list[str]:
    """The argv that invokes sibling tool `name` through the dispatcher.

    `tdd` itself is a shell function and cannot be exec'd, so this goes to the
    `tdd-exe` inside the tdd dir the dispatcher exported as TDD_DIR -- which
    also routes the sibling into *its* toolset, whatever this one is. Outside a
    dispatch (a direct development run) it falls back to a `tdd-exe` on PATH.
    Exposed on its own for callers that stream the child (Popen) rather than
    wait for it.
    """
    import shutil

    dir_ = os.environ.get("TDD_DIR")
    if dir_:
        exe = str(pathlib.Path(dir_) / "tdd-venvs" / "tdd" / "bin" / "tdd-exe")
        return [exe, "--dir", dir_, name, *args]
    exe = shutil.which("tdd-exe")
    if exe is None:
        raise RuntimeError("no tdd dir (TDD_DIR unset) and no tdd-exe on PATH")
    return [exe, name, *args]


def run_tool(name: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
    """Invoke a sibling tool in its own environment, through the dispatcher
    (see `tool_argv`)."""
    return subprocess.run(tool_argv(name, *args), **kwargs)
