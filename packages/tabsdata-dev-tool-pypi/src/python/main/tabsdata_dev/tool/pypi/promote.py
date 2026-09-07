#
# Copyright 2026 Tabsdata Inc.
#

"""pypi-wheels/staging/ -> pypi-wheels/prod/, locally. No AWS."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from tabsdata_dev.common.core.render import Renderer

from .indexhtml import render_all
from .tree import INDEX, clear_tree, link_or_copy, load_index, tree_files, write_index
from .yanked import YANKED, apply, load_masks


def promote(staging: Path, prod: Path, out: Renderer) -> int:
    """Make the local prod tree serve exactly what staging serves, under prod's
    own yanked.yaml.

    Same shape as generate: the destination is cleared first (its yanked.yaml
    kept) and its index is written last, so prod/ is never complete-looking
    while half built. The files are hardlinked from staging; the pages and the
    index are rendered again, because prod's yank list is its own -- staging's
    yanks do not carry over.
    """
    dists = load_index(staging)  # refuses if staging is incomplete
    files = {
        rel: p for rel, p in tree_files(staging).items() if rel.startswith("files/")
    }

    clear_tree(prod)
    masks = load_masks(prod)
    for rel, src in files.items():
        link_or_copy(src, prod / rel)

    dists = apply([replace(d, yanked=None) for d in dists], masks)
    for rel, text in render_all(dists).items():
        (prod / rel).parent.mkdir(parents=True, exist_ok=True)
        (prod / rel).write_text(text)
    write_index(prod, dists)

    yanked = [d for d in dists if d.yanked]
    out.info(
        f"{staging}/ -> {prod}/: {len(files)} file(s), {len(dists)} distribution(s)"
    )
    if yanked:
        out.info(f"{len(yanked)} file(s) yanked by {prod}/{YANKED}")
    return out.ok(
        f"{prod}/{INDEX} written — tree complete",
        tree=str(prod),
        files=len(files),
        distributions=len(dists),
        yanked=len(yanked),
    )
