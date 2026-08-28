#
# Copyright 2026 Tabsdata Inc.
#

"""Locating the shell assets this package carries.

This package holds no logic. It exists so that `scripts/unix/*.sh` and
`tddsrc.sh` can be installed into a venv and found again by path, without
anyone having to hardcode a site-packages layout.
"""

from __future__ import annotations

import pathlib
from importlib.resources import files

UNIX = "scripts/unix"
TEMPLATE = "tddsrc.sh"


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


def scripts_dir(family: str = "unix") -> pathlib.Path:
    """Directory holding the sourceable command files for a shell family."""
    return _root() / "scripts" / family


def source_template() -> str:
    """The tddsrc.sh template, with __TDD_DIR__ still unsubstituted."""
    return (_root() / TEMPLATE).read_text()
