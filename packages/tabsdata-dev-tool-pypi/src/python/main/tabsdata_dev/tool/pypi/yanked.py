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

from tabsdata_dev.common.core.errors import ToolError

from .model import Dist, normalize

YANKED = "yanked.yaml"

HEADER = """\
# Yanked files for this tree (PEP 592).
#
# Hand-edited. No tdd pypi command ever writes this file: generate (staging) and
# promote (prod) READ it and mark every matching file yanked, in the pages and in
# index.json. pip then refuses to select a yanked file unless the user pins that
# exact version -- so nobody new gets it, and nobody's lockfile breaks. Each tree
# has its own list; staging's is not copied to prod by promote.
#
# One entry per line, each a mask  <PACKAGE>-<VERSION>-<OS>  where * means ALL
# for that element:
#
#   - tabsdata-2.0.0-*                     every 2.0.0 wheel of tabsdata
#   - tabsdata-agent-*-macosx_11_0_arm64   every macOS wheel of tabsdata-agent
#   - "*-2.0.1-*"                          everything in 2.0.1  (quote a leading *)
#
# PACKAGE is the project name, tabsdata-agent or tabsdata_agent, either form.
# VERSION is the exact version string. OS is the wheel's platform tag:
# manylinux1_x86_64, macosx_11_0_arm64, win_amd64. Shell-style patterns work in
# every element. The mask that matched is what pip shows as the yank reason.
#
# Apply with: tdd pypi generate (staging) or tdd pypi promote (prod), then push.
"""


def yanked_path(tree: Path) -> Path:
    return tree / YANKED


def load_masks(tree: Path) -> list[str]:
    """The masks for a tree. A missing file is created with the header and no
    entries, so there is always one to edit; an existing file is never changed."""
    path = yanked_path(tree)
    if not path.exists():
        tree.mkdir(parents=True, exist_ok=True)
        path.write_text(HEADER)
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
