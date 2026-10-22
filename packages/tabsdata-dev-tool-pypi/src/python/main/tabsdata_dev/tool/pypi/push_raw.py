#
# Copyright 2026 Tabsdata Inc.
#

"""push --lane raw: raw-wheels/ -> the archive bucket, the source of truth's copy."""

from __future__ import annotations

from pathlib import Path

import boto3
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .config import DEFAULT_PARALLEL, Config
from .dist import sha256_file
from .plan import (
    DELETE,
    PUT,
    SKIP,
    Action,
    Local,
    execute,
    object_differs,
    remote_objects,
    report,
)
from .tree import read_manifest, version_dirs


def push_raw(
    raw: Path,
    cfg: Config,
    *,
    version: str | None = None,
    dry_run: bool = False,
    assume_yes: bool = False,
    force: bool = False,
    sync: bool = False,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> int:
    """Mirror raw-wheels/ (or one version of it) into the archive.

    Write-once by default: a filename already archived with other bytes is
    refused, listing every such file. --force overwrites them. --sync deletes
    what is archived but not in a MANIFEST here -- whole versions too, when no
    --version narrows the scope.
    """
    dirs = version_dirs(raw, version)
    if not dirs:
        raise ToolError(f"no version directories under {raw}/")

    local: dict[str, Local] = {}
    for version_dir in dirs:
        for name in read_manifest(version_dir, out):
            path = version_dir / name
            key = cfg.archive.key(version_dir.name, name)
            local[key] = Local(path, path.stat().st_size, sha256_file(path))
    out.info(f"{raw}/{version or '*'} ->")
    out.info(f"    {cfg.archive.s3}   (the archive is not served: no https://)")

    s3 = boto3.client("s3", region_name=cfg.region)
    prefix = cfg.archive.key(version, "") + "/" if version else cfg.archive.prefix
    remote = remote_objects(s3, cfg.archive.bucket, prefix, parallel)

    actions: list[Action] = []
    changed: list[tuple[str, str]] = []
    for key in sorted(local):
        f = local[key]
        r = remote.get(key)
        if r is None:
            actions.append(Action(PUT, key, "new", f.size, f.path, True, f.sha256))
            continue
        if r.sha256 is not None:
            why = (
                None
                if r.sha256 == f.sha256
                else f"sha256 {r.sha256[:12]} -> {f.sha256[:12]}"
            )
        else:
            why = object_differs(f.path, f.size, r.etag, r.size)
        if why is None:
            actions.append(Action(SKIP, key, "already archived"))
            continue
        changed.append((key, why))
        if force:
            actions.append(
                Action(PUT, key, f"re-archived ({why})", f.size, f.path, True, f.sha256)
            )

    if changed and not force:
        shown = "\n".join(f"  {k}\n    {why}" for k, why in changed[:10])
        raise ToolError(
            f"\n{len(changed)} filename(s) already archived with different bytes:"
            f"\n\n{shown}\n\n"
            "The archive is the byte record of what was released; overwriting it\n"
            "means a hash someone recorded at install time can no longer be checked.\n"
            "Release the fix under a new version instead. If these were never\n"
            "released, --force overwrites exactly these keys.\n"
        )

    # A version directory that is local but not archived is simply new. One that
    # is archived but not local only matters with --sync, and then it goes whole.
    orphans = sorted(k for k in remote if k not in local)
    if sync:
        gone_versions = sorted(
            {k[len(cfg.archive.prefix) :].split("/")[0] for k in orphans}
            - {d.name for d in dirs}
        )
        if gone_versions:
            out.warn(
                "--sync deletes whole archived version(s) not in "
                f"{raw}/: {', '.join(gone_versions)}"
            )
        deletes = [Action(DELETE, k, "not in raw-wheels (--sync)") for k in orphans]
        actions = deletes + actions
    elif orphans:
        out.info(
            f"{len(orphans)} archived object(s) not in {raw}/ left alone (no --sync)"
        )

    report(actions, cfg.archive.bucket, out)
    wrote = execute(
        actions,
        cfg.archive.bucket,
        s3,
        dry_run=dry_run,
        assume_yes=assume_yes,
        require_yes=False,
        parallel=parallel,
        out=out,
    )
    return out.ok(
        f"archive {cfg.archive.s3}: "
        + ("written" if wrote else "nothing written")
        + f" ({len(local)} wheel(s) in {len(dirs)} release(s))",
        bucket=cfg.archive.bucket,
        releases=[d.name for d in dirs],
        wheels=len(local),
        wrote=wrote,
        dry_run=dry_run,
    )
