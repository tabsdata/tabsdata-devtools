#
# Copyright 2026 Tabsdata Inc.
#

"""The edge: CloudFront invalidations for a serving lane.

`push` invalidates only what it wrote (see push.py). `cache-clean` invalidates
everything the lane's distribution holds, `/*`, for when the edge is suspected
of serving something the bucket no longer says -- a push interrupted after its
deletes, a change to the distribution itself, or plain doubt.
"""

from __future__ import annotations

from uuid import uuid4

import boto3

from tabsdata_dev.common.core.render import Renderer

from .config import Lane
from .plan import confirm

EVERYTHING = "/*"


def invalidate(lane: Lane, paths: list[str], *, reason: str) -> str:
    """One invalidation of these viewer paths on the lane's distribution; returns
    its id. Viewer paths, not S3 keys: `/simple/*`, not `pypi/simple/*`."""
    # CloudFront is a global service signed for us-east-1 whatever the shell says.
    cf = boto3.client("cloudfront", region_name="us-east-1")
    resp = cf.create_invalidation(
        DistributionId=lane.distribution,
        InvalidationBatch={
            "Paths": {"Quantity": len(paths), "Items": paths},
            "CallerReference": f"{reason}-{lane.bucket}-{uuid4()}",
        },
    )
    return resp["Invalidation"]["Id"]


def cache_clean(lane: Lane, out: Renderer, *, assume_yes: bool = False) -> int:
    """Invalidate everything at the edge for this lane. The bucket is untouched."""
    out.info(f"distribution {lane.distribution} ({lane.name}) serving")
    for url in lane.urls:
        out.info(f"    {url}")
    out.info(
        f"invalidate {EVERYTHING} — every cached object, files/ included; "
        "the next request for each goes back to the bucket"
    )
    confirm(
        "invalidate everything at the edge?",
        assume_yes=assume_yes,
        require_yes=lane.policy.require_yes,
    )
    inv = invalidate(lane, [EVERYTHING], reason="cache-clean")
    return out.ok(
        f"invalidation {inv} created on {lane.distribution}: {EVERYTHING} — the edge is clear in about a minute",
        lane=lane.name,
        distribution=lane.distribution,
        invalidation=inv,
        paths=EVERYTHING,
    )
