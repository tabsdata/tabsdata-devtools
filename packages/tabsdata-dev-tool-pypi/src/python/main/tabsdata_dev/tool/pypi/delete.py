#
# Copyright 2026 Tabsdata Inc.
#

"""delete --lane staging [--at NAME]: the lane's own tree, or one namespace,
out of the bucket and off the edge.

Staging only, by its parser: prod is the published index, and taking it down
is not a verb. A namespace is the usual target -- `push --at NAME` has no other
way to end -- and the lane's own tree goes the same way, its namespaces kept.
"""

from __future__ import annotations

import boto3
from tabsdata_dev.common.core.render import Renderer

from .cache import invalidate
from .config import DEFAULT_PARALLEL, Config, Lane
from .plan import DELETE, Action, execute, remote_objects, report
from .tree import INDEX


def plan_delete(keys: list[str], lane: Lane) -> list[Action]:
    """Every key, the index first and alone: from the first delete on, the
    target says it is incomplete, as a push that stopped halfway would."""
    index_key = lane.key(INDEX)
    head = (
        [Action(DELETE, index_key, "index first: incomplete from here", alone=True)]
        if index_key in keys
        else []
    )
    return head + [Action(DELETE, k, "delete") for k in sorted(keys) if k != index_key]


def delete(
    cfg: Config,
    lane: Lane,
    *,
    dry_run: bool = False,
    assume_yes: bool = False,
    parallel: int = DEFAULT_PARALLEL,
    out: Renderer,
) -> int:
    what = f"namespace {lane.at}" if lane.namespaced else f"{lane.name}'s own tree"
    out.info(f"delete {what}:")
    for line in lane.where("    ").splitlines():
        out.info(line)

    s3 = boto3.client("s3", region_name=cfg.region)
    # lane.owns: a namespace's prefix is its own; the lane's own tree leaves the
    # namespaces beside it alone.
    keys = list(
        remote_objects(
            s3, lane.bucket, lane.prefix, parallel, with_sha=False, keep=lane.owns
        )
    )
    if not keys:
        return out.ok(
            f"{lane.name}: nothing under {lane.s3} to delete",
            lane=lane.name,
            at=lane.at,
            bucket=lane.bucket,
            deleted=0,
            dry_run=dry_run,
        )

    actions = plan_delete(keys, lane)
    report(actions, lane.bucket, out, lane.distribution)
    if not execute(
        actions,
        lane.bucket,
        s3,
        dry_run=dry_run,
        assume_yes=assume_yes,
        require_yes=lane.policy.require_yes,
        parallel=parallel,
        out=out,
    ):
        return out.ok(
            f"{lane.name}: nothing deleted",
            lane=lane.name,
            at=lane.at,
            bucket=lane.bucket,
            deleted=0,
            dry_run=dry_run,
        )

    paths = (
        [f"/{lane.at}/*"]
        if lane.namespaced
        else ["/", "/index.html", "/index.json", "/simple/*", "/files/*"]
    )
    invalidate(lane, paths, reason="delete")
    out.info(f"invalidated {' '.join(paths)}")
    return out.ok(
        f"{lane.name}: deleted {len(actions)} object(s) of {what}",
        lane=lane.name,
        at=lane.at,
        bucket=lane.bucket,
        deleted=len(actions),
        invalidated=paths,
    )
