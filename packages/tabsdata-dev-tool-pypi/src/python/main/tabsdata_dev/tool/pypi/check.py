#
# Copyright 2026 Tabsdata Inc.
#

"""Is the index there? Locally, that means generate/promote finished; in the
lane, that the last push finished."""

from __future__ import annotations

from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

from .config import Config, Lane
from .tree import INDEX, index_path, metadata_path, read_index, wheel_path


def check_local(tree: Path, out: Renderer) -> int:
    dists = read_index(tree)
    if dists is None:
        raise ToolError(f"{index_path(tree)} is missing — {tree}/ is not complete")

    # The index says what should be here; make sure it is, without hashing.
    absent = [
        rel
        for d in dists
        for rel, p in (
            (f"files/{d.filename}", wheel_path(tree, d.filename)),
            (f"files/{d.filename}.metadata", metadata_path(tree, d.filename)),
        )
        if not p.exists()
    ]
    if absent:
        raise ToolError(
            f"{tree}/{INDEX} lists {len(absent)} file(s) that are not on disk:\n  "
            + "\n  ".join(absent[:10])
        )
    releases = sorted({d.release for d in dists})
    return out.ok(
        f"{tree}/{INDEX}: {len(dists)} distribution(s), "
        f"release(s) {', '.join(releases)}",
        tree=str(tree),
        distributions=len(dists),
        releases=releases,
    )


def check_remote(cfg: Config, lane: Lane, out: Renderer) -> int:
    s3 = boto3.client("s3", region_name=cfg.region)
    key = lane.key(INDEX)
    try:
        head = s3.head_object(Bucket=lane.bucket, Key=key)
    except ClientError as exc:
        if exc.response["Error"]["Code"] in ("404", "NoSuchKey", "NotFound"):
            raise ToolError(
                f"s3://{lane.bucket}/{key} is missing — the last push to "
                f"{lane.name} did not finish, or nothing was ever pushed"
            ) from exc
        raise
    sha = head.get("Metadata", {}).get("sha256", "-")
    return out.ok(
        f"s3://{lane.bucket}/{key}: {head['ContentLength']} bytes, "
        f"last modified {head['LastModified']:%Y-%m-%d %H:%M:%S}Z, sha256 {sha[:12]}",
        lane=lane.name,
        bucket=lane.bucket,
        key=key,
        sha256=sha,
    )
