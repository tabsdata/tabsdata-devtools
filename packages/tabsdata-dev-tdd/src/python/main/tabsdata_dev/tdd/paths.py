#
# Copyright 2026 Tabsdata Inc.
#

"""Locating the tdd dir and the source repo. Standard library only."""

from __future__ import annotations

import os
import pathlib

DEFAULT_DIR_NAME = ".tdd"

# Words tdd-exe answers to itself. Setting a dir up is `tdd-install`, a separate
# executable, and regenerating the catalog is `cargo make gen`, a build step;
# neither is something a user types after `tdd`.
BUILTINS = frozenset({"_doctor", "info"})

# Words no tool may be named: the builtins and `help`, which share one argument
# position with tool names. Shell command names are reserved too, but those
# are discovered from the shell package rather than listed here.
RESERVED = BUILTINS | {"help"}


def tdd_dir(explicit: str | None = None) -> pathlib.Path:
    """--dir  ->  $TDD_DIR  ->  ~/.tdd"""
    if explicit:
        return pathlib.Path(explicit).expanduser().resolve()
    env = os.environ.get("TDD_DIR")
    if env:
        return pathlib.Path(env).expanduser().resolve()
    return pathlib.Path.home() / DEFAULT_DIR_NAME


def venvs_dir(dir_: pathlib.Path) -> pathlib.Path:
    return dir_ / "tdd-venvs"


def repo_root() -> pathlib.Path | None:
    """Walk up from this module to the source checkout, if we are installed
    editable. Returns None for a wheel install, where no repo is present."""
    here = pathlib.Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "packages" / "tabsdata-dev-tdd"
        if candidate.is_dir():
            return parent
    return None


UV_MISSING = "uv is a hard requirement, install it"


def require_uv() -> str:
    """Return the path to uv, or fail. uv is not optional anywhere in tdd."""
    import shutil

    found = shutil.which("uv")
    if found is None:
        raise UvMissing(UV_MISSING)
    return found


class UvMissing(RuntimeError):
    pass
