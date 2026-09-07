#
# Copyright 2026 Tabsdata Inc.
#

"""Local trees: raw-wheels/<VERSION>/ with its MANIFEST, and the lane trees under
pypi-wheels/<lane>/ with their root index.json."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .model import Dist

MANIFEST = "MANIFEST"

#: The root index: every file in the tree with its sha256, written LAST by
#: generate/promote and put LAST by push. Its presence means "complete"; its
#: absence means whatever produced this tree did not finish.
INDEX = "index.json"
INDEX_FORMAT = 1

#: The one file in a tree that is a human's, not the tool's (see yanked.py). It
#: survives clear_tree, is not part of tree_files, and so is never pushed,
#: fetched or pruned.
YANKED = "yanked.yaml"


def lane_tree(root: Path, lane: str) -> Path:
    """pypi-wheels/<lane>/ -- the local copy of what that lane serves."""
    return root / lane


# ------------------------------------------------------------------ raw-wheels


def read_manifest(version_dir: Path, out: Renderer | None = None) -> list[str]:
    """The explicit allowlist for one release. One wheel filename per line.

    Listed and present -> processed. Present but not listed -> ignored, and
    reported. Listed but absent -> hard error. That is what makes an incomplete
    release a failure rather than something to notice in a diff.
    """
    path = version_dir / MANIFEST
    if not path.exists():
        raise ToolError(
            f"{path} is missing.\n"
            f"  create it with:  (cd {version_dir} && ls *.whl > {MANIFEST})"
        )

    names: list[str] = []
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            names.append(line)
    if not names:
        raise ToolError(f"{path} lists no files")

    dupes = sorted({n for n in names if names.count(n) > 1})
    if dupes:
        raise ToolError(f"{path} lists duplicates: {', '.join(dupes)}")

    present = {p.name for p in version_dir.glob("*.whl")}
    absent = [n for n in names if n not in present]
    if absent:
        raise ToolError(
            f"{path} lists {len(absent)} file(s) not present in {version_dir}:\n  "
            + "\n  ".join(absent)
        )

    # A wheel sitting beside the MANIFEST that the MANIFEST does not name is
    # not an error -- the MANIFEST is the release, the directory is a workspace
    # -- but it is worth saying out loud, since "I dropped it in and it did not
    # ship" is otherwise a silent surprise.
    if out is not None:
        for n in sorted(present - set(names)):
            out.info(f"    ignored    {n}  (not in {MANIFEST})")

    return names


def version_dirs(raw: Path, version: str | None = None) -> list[Path]:
    """raw-wheels/<VERSION>/ directories, all of them or one, sorted."""
    if version:
        d = raw / version
        if not d.is_dir():
            raise ToolError(f"{d} does not exist")
        return [d]
    if not raw.exists():
        return []
    return sorted(p for p in raw.iterdir() if p.is_dir())


# ------------------------------------------------------------------ lane trees


def metadata_path(tree: Path, filename: str) -> Path:
    return tree / "files" / f"{filename}.metadata"


def wheel_path(tree: Path, filename: str) -> Path:
    return tree / "files" / filename


def index_path(tree: Path) -> Path:
    return tree / INDEX


def read_index(tree: Path) -> list[Dist] | None:
    """The root index, or None when the tree is absent or incomplete."""
    path = index_path(tree)
    if not path.exists():
        return None
    try:
        doc = json.loads(path.read_text())
        return [Dist(**f) for f in doc["files"]]
    except (TypeError, ValueError, KeyError) as exc:
        raise ToolError(f"{path}: malformed index: {exc}") from exc


def load_index(tree: Path) -> list[Dist]:
    """The root index, or a refusal that says what to run."""
    dists = read_index(tree)
    if dists is None:
        raise ToolError(
            f"{index_path(tree)} is missing — {tree}/ is not a complete tree.\n"
            "  It is written last, so either nothing generated this tree or the\n"
            "  generation did not finish. Run: tdd pypi generate   (or promote)"
        )
    return dists


def write_index(tree: Path, dists: list[Dist]) -> None:
    """Write the root index. Call this LAST: it is what marks the tree complete."""
    doc = {
        "format": INDEX_FORMAT,
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "releases": sorted({d.release for d in dists}),
        "files": [asdict(d) for d in sorted(dists, key=lambda d: d.filename)],
    }
    tree.mkdir(parents=True, exist_ok=True)
    index_path(tree).write_text(json.dumps(doc, indent=2) + "\n")


def clear_tree(tree: Path) -> None:
    """Remove a lane tree -- everything but yanked.yaml, which is the operator's.
    The index goes first, so a tree that is being rebuilt never looks complete
    while it is half gone."""
    index_path(tree).unlink(missing_ok=True)
    if not tree.exists():
        return
    keep = tree / YANKED
    masks = keep.read_bytes() if keep.exists() else None
    shutil.rmtree(tree)
    if masks is not None:
        tree.mkdir(parents=True)
        keep.write_bytes(masks)


def tree_files(tree: Path) -> dict[str, Path]:
    """Every regular file in the tree, tree-relative, EXCLUDING the root index --
    callers place that one themselves, first or last -- and yanked.yaml, which is
    not content but the operator's instructions for producing it."""
    if not tree.exists():
        return {}
    skip = {index_path(tree), tree / YANKED}
    return {
        p.relative_to(tree).as_posix(): p
        for p in sorted(tree.rglob("*"))
        if p.is_file() and p not in skip
    }


def html_pages(tree: Path) -> dict[str, bytes]:
    """Every generated HTML file currently on disk, tree-relative."""
    out: dict[str, bytes] = {}
    root = tree / "index.html"
    if root.exists():
        out["index.html"] = root.read_bytes()
    simple = tree / "simple"
    if simple.exists():
        for p in sorted(simple.rglob("*.html")):
            out[p.relative_to(tree).as_posix()] = p.read_bytes()
    return out


def link_or_copy(src: Path, dst: Path) -> None:
    """Hardlink so a 30 MB wheel is not duplicated; copy across filesystems.

    Always replaces dst: os.link is a metadata operation, and the copy2 fallback
    only costs anything when the two trees sit on different volumes.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.unlink(missing_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)
