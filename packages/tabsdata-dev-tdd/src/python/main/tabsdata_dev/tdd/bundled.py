#
# Copyright 2026 Tabsdata Inc.
#
"""tdd's own resource files, from <pkg>/src/resources/main. Standard library
only: the half of common.core.resources that tdd needs -- the same two layouts,
a wheel's `resources/` beside this module or the checkout's folder -- without
Jinja2. tdd's one template is a string.Template. Not named `resources`: in a
wheel that is the folder beside it."""

from __future__ import annotations

import pathlib
import string
from importlib.resources import files

#: The folder name a wheel uses, next to this module.
WHEEL_FOLDER = "resources"
#: How far above this module the checkout's `src` is (python/main/tabsdata_dev/tdd).
_SRC_PARENT = 3


def main_folder() -> pathlib.Path:
    here = pathlib.Path(str(files("tabsdata_dev.tdd")))
    beside = here / WHEEL_FOLDER
    if beside.is_dir():
        return beside
    checkout = here.parents[_SRC_PARENT] / "resources" / "main"
    if checkout.is_dir():
        return checkout
    raise FileNotFoundError(f"tdd resources not found at {beside} nor {checkout}")


def render(name: str, /, **values: str) -> str:
    """Fill the string.Template `name`; a placeholder left without a value is
    an error (KeyError), never an empty string."""
    text = (main_folder() / name).read_text(encoding="utf-8")
    return string.Template(text).substitute(values)
