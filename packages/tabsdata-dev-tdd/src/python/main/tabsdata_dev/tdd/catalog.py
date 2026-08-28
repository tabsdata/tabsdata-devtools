#
# Copyright 2026 Tabsdata Inc.
#

"""Reading, writing and comparing catalogs. Standard library only."""

from __future__ import annotations

import json
import pathlib
from importlib.resources import files

CATALOG_NAME = "catalog.json"


def shipped() -> dict:
    """The catalog baked into this installed package."""
    return json.loads(files("tabsdata_dev.tdd").joinpath(CATALOG_NAME).read_text())


def shipped_path() -> pathlib.Path:
    return pathlib.Path(str(files("tabsdata_dev.tdd").joinpath(CATALOG_NAME)))


def installed(dir_: pathlib.Path) -> dict:
    """The catalog copied into a tdd dir by `tdd init`."""
    path = dir_ / CATALOG_NAME
    if not path.is_file():
        raise NotInitialized(dir_)
    return json.loads(path.read_text())


def write(path: pathlib.Path, catalog: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n")


def is_stale(dir_: pathlib.Path) -> bool:
    """True when a tdd dir was built from a different catalog than the one we ship."""
    try:
        return installed(dir_).get("fingerprint") != shipped().get("fingerprint")
    except NotInitialized:
        return False


class NotInitialized(Exception):
    def __init__(self, dir_: pathlib.Path):
        super().__init__(f"{dir_} is not initialized; run: tdd-install --dir {dir_}")
        self.dir = dir_
