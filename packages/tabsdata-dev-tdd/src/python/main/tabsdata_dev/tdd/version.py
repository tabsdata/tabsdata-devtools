#
# Copyright 2026 Tabsdata Inc.
#

"""The release version, read from the repo's VERSION file. Standard library only.

One file at the repo root is the single source: every package's wheel version
is derived from it by hatchling, and `tabsdata-dev-tdd` additionally ships a
copy as package data so a wheels-mode install -- which has no checkout -- can
still say what it is. `tdd init` copies it into the tdd dir, and `tdd
--version` reports that copy: it is the version of what was actually built
there, which can lag the checkout in editable mode.
"""

from __future__ import annotations

import pathlib
from importlib.resources import files

from . import paths

VERSION_NAME = "VERSION"


def shipped() -> str:
    """The version this installed package carries.

    A wheel has VERSION beside this module, put there by force-include. An
    editable install copies nothing, so the file is still at the repo root --
    the same asymmetry tabsdata_dev.shell absorbs for its assets.
    """
    beside = files("tabsdata_dev.tdd").joinpath(VERSION_NAME)
    if beside.is_file():
        return beside.read_text().strip()
    root = paths.repo_root()
    if root is not None and (root / VERSION_NAME).is_file():
        return (root / VERSION_NAME).read_text().strip()
    raise FileNotFoundError(
        f"{VERSION_NAME} not found beside {beside} nor in a checkout"
    )


def installed(dir_: pathlib.Path) -> str | None:
    """The version `tdd init` stamped into a tdd dir, or None if never initialized."""
    path = dir_ / VERSION_NAME
    return path.read_text().strip() if path.is_file() else None


def current(dir_: pathlib.Path) -> str:
    """What `tdd --version` reports: the tdd dir's stamp, else the shipped one."""
    return installed(dir_) or shipped()


def stamp(dir_: pathlib.Path) -> None:
    (dir_ / VERSION_NAME).write_text(shipped() + "\n")
