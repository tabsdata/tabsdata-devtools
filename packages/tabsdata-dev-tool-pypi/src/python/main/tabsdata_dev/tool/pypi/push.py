#
# Copyright 2026 Tabsdata Inc.
#

"""push --lane staging|prod [--at NAME]: pypi-wheels/<lane>/ -> that serving
bucket, exactly -- or into namespace NAME beside the lane's own tree."""

from __future__ import annotations

import tempfile
from pathlib import Path

import boto3
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .cache import invalidate
from .config import DEFAULT_PARALLEL, RELEASE_PATHS, Config, Lane
from .dist import sha256_file
from .git import assert_committed_and_pushed
from .indexhtml import render_namespace
from .plan import (
    DELETE,
    PUT,
    Local,
    Remote,
    execute,
    plan_mirror,
    remote_objects,
    report,
)
from .tree import INDEX, index_path, load_index, tree_files


def _local_files(tree: Path) -> dict[str, Local]:
    """Every file in the tree with its sha256. Wheels take theirs from the index
    -- generate hashed the very same bytes -- so a push does not re-hash 6 GB;
    everything else is small and hashed here."""
    by_wheel = {f"files/{d.filename}": d.sha256 for d in load_index(tree)}
    out: dict[str, Local] = {}
    for rel, path in tree_files(tree).items():
        sha = by_wheel.get(rel) or sha256_file(path)
        out[rel] = Local(path, path.stat().st_size, sha)
    idx = index_path(tree)
    out[INDEX] = Local(idx, idx.stat().st_size, sha256_file(idx))
    return out


def _namespace_files(tree: Path, stage: Path) -> dict[str, Local]:
    """The tree as namespace NAME serves it: files/ and the index as they are,
    the pages rendered for the namespace's layout into `stage`. Nothing of the
    tree is copied -- a wheel's Local points at the tree's own file."""
    out = {
        rel: f
        for rel, f in _local_files(tree).items()
        if rel == INDEX or rel.startswith("files/")
    }
    for rel, text in render_namespace(load_index(tree)).items():
        path = stage / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
        out[rel] = Local(path, path.stat().st_size, sha256_file(path))
    return out


def _assert_archived(s3, cfg: Config, tree: Path, parallel: int, out: Renderer) -> None:
    """Prod may only serve bytes that exist in the archive, byte for byte."""
    dists = load_index(tree)
    archived: dict[str, Remote] = remote_objects(
        s3, cfg.archive.bucket, cfg.archive.prefix, parallel
    )
    problems = []
    for d in dists:
        key = cfg.archive.key(d.release, d.filename)
        r = archived.get(key)
        if r is None:
            problems.append(f"{key}   NOT ARCHIVED")
        elif r.sha256 is not None and r.sha256 != d.sha256:
            problems.append(f"{key}   sha256 {r.sha256[:12]} != {d.sha256[:12]}")
        elif r.sha256 is None and r.size != d.size:
            problems.append(f"{key}   size {r.size} != {d.size}")
    if problems:
        raise ToolError(
            f"\nrefusing — {len(problems)} wheel(s) not correctly archived:\n  "
            + "\n  ".join(problems[:10])
            + "\n\nrun: tdd pypi push --lane raw\n"
        )
    out.info(
        f"archive check: {len(dists)} wheel(s) present in s3://{cfg.archive.bucket}"
    )


def push(
    root: Path,
    cfg: Config,
    lane: Lane,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    full: bool = False,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> int:
    tree = root / lane.name
    load_index(tree)  # refuses if the tree is incomplete
    out.info(f"{tree}/ -> namespace {lane.at}" if lane.namespaced else f"{tree}/ ->")
    for line in lane.where("    ").splitlines():
        out.info(line)

    s3 = boto3.client("s3", region_name=cfg.region)

    # Prod's two gates, before anything is listed or written.
    if lane.policy.require_pushed:
        head = assert_committed_and_pushed(RELEASE_PATHS, cfg.release_ref)
        out.info(f"git check: {head[:12]} is in {cfg.release_ref}")
    if lane.policy.require_archived:
        _assert_archived(s3, cfg, tree, parallel, out)

    # A namespace's pages are rendered for it, into a directory that has to
    # outlive the uploads; the lane's own push reads the tree as it is.
    with tempfile.TemporaryDirectory(prefix="tdd-pypi-pages-") as stage:
        local = (
            _namespace_files(tree, Path(stage))
            if lane.namespaced
            else _local_files(tree)
        )
        # lane.owns: the lane's own objects only, so a namespace beside them is
        # neither compared, pruned nor --full deleted.
        remote = remote_objects(
            s3,
            lane.bucket,
            lane.prefix,
            parallel,
            with_sha=not full,
            keep=lane.owns,
        )
        if full:
            out.warn(
                f"--full: everything under s3://{lane.bucket}/{lane.prefix} is "
                "deleted first, then the whole tree is uploaded"
                + ("" if lane.namespaced else " (namespaces beside it are kept)")
            )
        actions = plan_mirror(local, remote, lane, full=full)
        report(actions, lane.bucket, out, lane.distribution)
        wrote = execute(
            actions,
            lane.bucket,
            s3,
            dry_run=dry_run,
            assume_yes=assume_yes,
            require_yes=lane.policy.require_yes,
            parallel=parallel,
            out=out,
        )
    if not wrote:
        return out.ok(
            f"{lane.name}: nothing written",
            lane=lane.name,
            at=lane.at,
            bucket=lane.bucket,
            wrote=False,
            dry_run=dry_run,
        )

    if lane.namespaced:
        # The namespace whole, files/ included: rebuilding a wheel under an
        # unchanged filename is the usual case for a developer's own index.
        paths = [f"/{lane.at}/*"]
    else:
        # Pages and the index are short-lived at the edge; files/ are cached for
        # a year as immutable, so they are only cleared when a files/ URL
        # stopped answering or started answering differently.
        paths = ["/", "/index.html", "/index.json", "/simple/*"]
        files_prefix = lane.key("files/")
        if any(
            a.key.startswith(files_prefix)
            and (a.verb == DELETE or (a.verb == PUT and a.key in remote))
            for a in actions
        ):
            paths.append("/files/*")
    invalidate(lane, paths, reason="push")
    out.info(f"invalidated {' '.join(paths)}")
    return out.ok(
        f"{lane.name}: pushed — live in about a minute at {' and '.join(lane.urls)}",
        lane=lane.name,
        at=lane.at,
        bucket=lane.bucket,
        wrote=True,
        invalidated=paths,
        urls=lane.urls,
    )
