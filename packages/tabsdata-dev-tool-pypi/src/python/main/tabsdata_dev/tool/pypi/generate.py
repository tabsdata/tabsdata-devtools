#
# Copyright 2026 Tabsdata Inc.
#

"""raw-wheels/ -> pypi-wheels/staging/, from scratch every time -- every
release under raw-wheels/, or one. No AWS."""

from __future__ import annotations

from pathlib import Path

from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .dist import describe
from .indexhtml import render_all
from .model import Dist
from .tree import (
    INDEX,
    clear_tree,
    link_or_copy,
    metadata_path,
    read_manifest,
    version_dirs,
    wheel_path,
    write_index,
)
from .yanked import YANKED, apply, load_masks


def generate(raw: Path, tree: Path, out: Renderer, version: str | None = None) -> int:
    """Rebuild the staging tree from raw-wheels/, the source of truth -- every
    release under it, or with `version` that one release alone.

    The tree is deleted first and the root index is written last, so at no
    point does a half-built tree look complete: no index.json means generation
    did not finish, and every consumer of the tree (serve, promote, push, check)
    refuses on that. A one-release tree is built the same way, from scratch:
    what the tree held before is gone, and a push makes its target exactly it.
    """
    dirs = version_dirs(raw, version)  # a named release that is absent refuses here
    if not dirs:
        raise ToolError(f"no version directories under {raw}/")

    # Read and validate every MANIFEST before deleting anything, so a typo in
    # one release does not leave staging empty.
    plan: list[tuple[Path, str, Path]] = []
    seen: dict[str, str] = {}
    for version_dir in dirs:
        for name in read_manifest(version_dir, out):
            if name in seen:
                raise ToolError(
                    f"{name} is listed by both {seen[name]} and {version_dir.name}. "
                    "A filename can belong to one release only."
                )
            seen[name] = version_dir.name
            plan.append((version_dir, name, version_dir / name))

    clear_tree(tree)
    out.info(f"{tree}/ cleared (except {YANKED})")
    masks = load_masks(tree)

    dists: list[Dist] = []
    for version_dir, name, whl in plan:
        d, raw_meta = describe(whl, version_dir.name)
        link_or_copy(whl, wheel_path(tree, name))
        metadata_path(tree, name).write_bytes(raw_meta)
        dists.append(d)
    for version_dir in dirs:
        n = sum(1 for d in dists if d.release == version_dir.name)
        out.info(f"{version_dir.name}: {n} wheel(s)")

    dists = apply(dists, masks)
    yanked = [d for d in dists if d.yanked]
    if yanked:
        out.info(f"{len(yanked)} file(s) yanked by {tree}/{YANKED}")

    for rel, text in render_all(dists).items():
        path = tree / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)

    write_index(tree, dists)
    return out.ok(
        f"{tree}/{INDEX} written — tree complete: {len(dists)} distribution(s), "
        f"{len({d.project for d in dists})} project(s), {len(dirs)} release(s)",
        tree=str(tree),
        distributions=len(dists),
        projects=len({d.project for d in dists}),
        releases=[d.name for d in dirs],
        yanked=len(yanked),
    )
