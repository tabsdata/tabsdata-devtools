#
# Copyright 2026 Tabsdata Inc.
#

"""fetch --lane raw|staging|prod: a bucket back onto disk, exactly."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import boto3
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .config import DEFAULT_PARALLEL, Config, Lane
from .plan import confirm, remote_index
from .pull import Pull, pull_all
from .tree import INDEX, MANIFEST, index_path

_MARKER = ".empty"  # keeps an otherwise-empty directory in git; never in a bucket


def _fail_if_any(failures: list[str]) -> None:
    if failures:
        raise ToolError(
            f"\n{len(failures)} download(s) failed:\n  " + "\n  ".join(failures[:10])
        )


def _prune(
    root: Path,
    keep: set[Path],
    exempt: Callable[[Path], bool],
    out: Renderer,
    *,
    assume_yes: bool,
) -> int:
    """--sync: delete every regular file under root that the lane does not hold,
    then remove emptied directories. Listed and confirmed first."""
    victims = sorted(
        p for p in root.rglob("*") if p.is_file() and p not in keep and not exempt(p)
    )
    if not victims:
        out.info("sync: nothing here that the lane does not hold")
        return 0
    out.info(f"sync: {len(victims)} local file(s) the lane does not hold:")
    for v in victims:
        out.info(f"    delete  {v.relative_to(root)}")
    confirm("delete these files?", assume_yes=assume_yes)
    for v in victims:
        v.unlink()
    for d in sorted((d for d in root.rglob("*") if d.is_dir()), reverse=True):
        if not any(d.iterdir()):
            d.rmdir()
    out.info(f"pruned {len(victims)} file(s)")
    return len(victims)


# ------------------------------------------------------------------ --lane raw


def _write_manifest(version_dir: Path, names: list[str]) -> str:
    """Recreate MANIFEST from what the archive holds -- push --lane raw uploads
    exactly the MANIFEST entries and never the file itself, so the listing *is*
    the manifest. A MANIFEST already on disk is the author's and is left alone.
    -> 'written', 'kept', or 'kept (differs)'."""
    path = version_dir / MANIFEST
    if not path.exists():
        path.write_text("\n".join(names) + "\n")
        return "written"
    listed = {
        line.split("#", 1)[0].strip()
        for line in path.read_text().splitlines()
        if line.split("#", 1)[0].strip()
    }
    return "kept" if listed == set(names) else "kept (differs)"


def fetch_raw(
    raw: Path,
    cfg: Config,
    *,
    version: str | None = None,
    force: bool = False,
    sync: bool = False,
    assume_yes: bool = False,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> int:
    s3 = boto3.client("s3", region_name=cfg.region)
    prefix = cfg.archive.key(version, "") + "/" if version else cfg.archive.prefix
    remote = remote_index(s3, cfg.archive.bucket, prefix)

    pulls: list[Pull] = []
    for key, (etag, size) in sorted(remote.items()):
        parts = key[len(cfg.archive.prefix) :].split("/")
        if len(parts) != 2 or not all(parts):
            continue  # not <version>/<wheel>: not part of any release
        v, name = parts
        pulls.append(Pull(key, etag, size, raw / v / name, f"{v}/{name}"))
    if not pulls:
        raise ToolError(f"nothing archived under s3://{cfg.archive.bucket}/{prefix}")

    by_version: dict[str, list[str]] = {}
    for p in pulls:
        by_version.setdefault(p.dst.parent.name, []).append(p.dst.name)
    out.info(f"lane raw: s3://{cfg.archive.bucket}/{prefix} -> {raw}/")
    out.info("    (the archive is not served: no https://)")
    out.info(f"{len(by_version)} version(s): {', '.join(sorted(by_version))}")

    root = raw / version if version else raw
    if sync and root.exists() and not version:
        local_only = sorted(
            d.name for d in root.iterdir() if d.is_dir() and d.name not in by_version
        )
        if local_only:
            out.warn(
                "not in the archive, --sync removes them entirely: "
                + ", ".join(local_only)
            )

    counts, failures = pull_all(
        s3, cfg.archive.bucket, pulls, parallel, out, force=force
    )
    _fail_if_any(failures)

    # Only once every wheel of a version is on disk: a MANIFEST naming a file
    # that is not there makes generate fail hard, by design.
    for v in sorted(by_version):
        outcome = _write_manifest(raw / v, sorted(by_version[v]))
        out.info(f"{raw / v / MANIFEST}: {outcome}")
        if outcome == "kept (differs)":
            out.warn(
                f"the MANIFEST already in {raw / v}/ does not list the same files "
                f"the archive holds for {v}. It was left as is."
            )

    pruned = 0
    if sync:
        archived_dirs = {p.dst.parent for p in pulls}
        pruned = _prune(
            root,
            {p.dst for p in pulls},
            lambda p: (
                p.name == _MARKER or (p.name == MANIFEST and p.parent in archived_dirs)
            ),
            out,
            assume_yes=assume_yes,
        )
    return out.ok(
        f"raw: {counts['fetched']} fetched, {counts['have']} already present, "
        f"{len(by_version)} release(s) under {raw}/",
        lane="raw",
        bucket=cfg.archive.bucket,
        releases=sorted(by_version),
        pruned=pruned,
        **counts,
    )


# --------------------------------------------------------- --lane staging|prod


def fetch_lane(
    root: Path,
    cfg: Config,
    lane: Lane,
    *,
    force: bool = False,
    sync: bool = False,
    assume_yes: bool = False,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> int:
    """The lane, exactly, into pypi-wheels/<lane>/. The index comes down last,
    so an interrupted fetch leaves a tree that says so."""
    tree = root / lane.name
    s3 = boto3.client("s3", region_name=cfg.region)
    # The lane's own objects: a namespace beside them (push --at) is a
    # developer's, never part of pypi-wheels/<lane>/.
    remote = {
        k: v
        for k, v in remote_index(s3, lane.bucket, lane.prefix).items()
        if lane.owns(k)
    }
    if not remote:
        raise ToolError(f"nothing under s3://{lane.bucket}/{lane.prefix}")

    index_key = lane.key(INDEX)
    pulls: list[Pull] = []
    for key, (etag, size) in sorted(remote.items()):
        rel = key[len(lane.prefix) :]
        if not rel or rel.endswith("/") or key == index_key:
            continue
        pulls.append(Pull(key, etag, size, tree / rel, rel))
    out.info(f"lane {lane.name} -> {tree}/, from")
    for line in lane.where("    ").splitlines():
        out.info(line)
    if index_key not in remote:
        out.warn(
            f"s3://{lane.bucket}/{index_key} is missing — the last push to "
            f"{lane.name} did not finish. Fetching what is there; the tree will not be "
            "complete either."
        )

    # The local index goes first: while files are changing underneath it, the
    # tree must not claim to be complete.
    index_path(tree).unlink(missing_ok=True)
    counts, failures = pull_all(s3, lane.bucket, pulls, parallel, out, force=force)
    _fail_if_any(failures)

    pruned = 0
    if sync:
        pruned = _prune(
            tree,
            {p.dst for p in pulls},
            lambda p: p.name == _MARKER,
            out,
            assume_yes=assume_yes,
        )

    complete = index_key in remote
    if complete:
        etag, size = remote[index_key]
        _counts, failures = pull_all(
            s3,
            lane.bucket,
            [Pull(index_key, etag, size, index_path(tree), INDEX)],
            1,
            out,
            force=True,
        )
        _fail_if_any(failures)
        out.info(f"{tree}/{INDEX} written — tree complete")
    return out.ok(
        f"{lane.name}: {counts['fetched']} fetched, {counts['have']} already present"
        + ("" if complete else f" — no {INDEX}, the tree is NOT complete"),
        lane=lane.name,
        bucket=lane.bucket,
        tree=str(tree),
        complete=complete,
        pruned=pruned,
        **counts,
    )
