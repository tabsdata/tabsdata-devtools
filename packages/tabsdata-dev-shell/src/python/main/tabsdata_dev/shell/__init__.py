#
# Copyright 2026 Tabsdata Inc.
#

"""Locating the shell assets this package carries.

This package holds no logic. It exists so that `scripts/<family>/*` and the
loader templates can be installed into a venv and found again by path, without
anyone having to hardcode a site-packages layout.

Two families carry the same commands: `unix` is POSIX sh (bash 3.2 and zsh),
`powershell` is PowerShell 7, which runs on macOS, Linux and Windows alike --
so a family is the shell the user is in, not the operating system they are on.
Each has its own loader template beside this module, and `tdd-install` writes
both into a tdd dir, so one dir serves either shell.
"""

from __future__ import annotations

import pathlib
from importlib.resources import files

UNIX = "unix"
POWERSHELL = "powershell"
FAMILIES = (UNIX, POWERSHELL)

#: The loader template of each family, the name it is installed under in a tdd
#: dir, the suffix its command files carry, and its shared helper file (which
#: is not a command).
TEMPLATES = {UNIX: "tddsrc.sh", POWERSHELL: "tddsrc.ps1"}
INSTALLED = {UNIX: "tdd-source.sh", POWERSHELL: "tdd-source.ps1"}
SUFFIXES = {UNIX: ".sh", POWERSHELL: ".ps1"}
COMMON = {UNIX: "common.sh", POWERSHELL: "common.ps1"}

#: What `_root()` probes for to tell a wheel layout from a checkout.
TEMPLATE = TEMPLATES[UNIX]


def _root() -> pathlib.Path:
    """Where the shell assets actually are.

    A wheel install has them beside this module, put there by force-include. An
    editable install copies nothing, so they are still at the package root of
    the checkout -- force-include has no effect on a link. Both layouts are
    normal; check for the template to tell them apart.
    """
    beside = pathlib.Path(str(files("tabsdata_dev.shell")))
    if (beside / TEMPLATE).is_file():
        return beside
    checkout = beside.parents[4]  # .../<pkg>/src/python/main/tabsdata_dev/shell
    if (checkout / TEMPLATE).is_file():
        return checkout
    raise FileNotFoundError(f"shell assets not found beside {beside} nor at {checkout}")


def scripts_dir(family: str = UNIX) -> pathlib.Path:
    """Directory holding the sourceable command files for a shell family."""
    return _root() / "scripts" / family


def source_template(family: str = UNIX) -> str:
    """The family's loader template, with __TDD_DIR__ still unsubstituted."""
    return (_root() / TEMPLATES[family]).read_text(encoding="utf-8")
