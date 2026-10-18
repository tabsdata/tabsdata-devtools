#
# Copyright 2026 Tabsdata Inc.
#

"""yanked.yaml: the hand-edited list of masks that marks files yanked (PEP 592).

One per tree -- pypi-wheels/staging/yanked.yaml, pypi-wheels/prod/yanked.yaml --
read by generate and promote respectively and written by nothing but a human.
"""

from __future__ import annotations

from dataclasses import replace
from fnmatch import fnmatchcase
from pathlib import Path

import yaml

from tabsdata_dev.common.core import resources
from tabsdata_dev.common.core.errors import ToolError

from .model import Dist, normalize

YANKED = "yanked.yaml"
PACKAGE = "tabsdata_dev.tool.pypi"

#: What a new yanked.yaml starts as: the instructions, as comments, and no
#: entries. A file in this package's resources, written out byte for byte.
NEW_FILE = "yanked.yaml"


def yanked_path(tree: Path) -> Path:
    return tree / YANKED


def load_masks(tree: Path) -> list[str]:
    """The masks for a tree. A missing file is created with the header and no
    entries, so there is always one to edit; an existing file is never changed."""
    path = yanked_path(tree)
    if not path.exists():
        tree.mkdir(parents=True, exist_ok=True)
        path.write_text(resources.text(PACKAGE, NEW_FILE))
        return []
    doc = yaml.safe_load(path.read_text())
    if doc is None:
        return []
    if not isinstance(doc, list) or not all(isinstance(m, str) for m in doc):
        raise ToolError(f"{path}: expected a list of masks, one per line ('- mask')")
    for m in doc:
        parse_mask(m, path)
    return doc


def parse_mask(mask: str, path: Path) -> tuple[str, str, str]:
    """'<PACKAGE>-<VERSION>-<OS>' -> (package, version, os). PACKAGE may contain
    dashes; VERSION and OS never do, so the split is from the right."""
    parts = mask.rsplit("-", 2)
    if len(parts) != 3 or not all(parts):
        raise ToolError(
            f"{path}: {mask!r} is not a <PACKAGE>-<VERSION>-<OS> mask "
            "(use * for an element that means all)"
        )
    return parts[0], parts[1], parts[2]


def _platform(filename: str) -> str:
    return filename[: -len(".whl")].rsplit("-", 1)[-1]


def matches(d: Dist, mask: str) -> bool:
    pkg, ver, os_ = parse_mask(mask, Path(YANKED))
    return (
        fnmatchcase(d.project, normalize(pkg))
        and fnmatchcase(d.version, ver)
        and fnmatchcase(_platform(d.filename), os_)
    )


def apply(dists: list[Dist], masks: list[str]) -> list[Dist]:
    """Every dist with `yanked` set to the first mask that matches it, or None.
    Starts from a clean slate: a mask that is gone un-yanks."""
    out = []
    for d in dists:
        hit = next((m for m in masks if matches(d, m)), None)
        out.append(replace(d, yanked=hit))
    return out
