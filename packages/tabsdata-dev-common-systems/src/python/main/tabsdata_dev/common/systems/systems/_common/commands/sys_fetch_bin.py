#
# Copyright 2026 Tabsdata Inc.
#

"""Fetch the binaries a system needs: its docker images, or a native system's archives.

``--type ALL`` fetches them for every system that has any, ``--type a,b`` for
the listed ones, de-duplicated across the selection. A container's images are
pulled from their registry, or built here for one whose image is not published;
a native system's archives are downloaded into their cache.

A system with nothing to fetch -- a remote service, a managed instance -- is a
warning and a skip, never a failure, so fetching everything in one go stays a
single command whatever the selection holds.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, constants, systems
from tabsdata_dev.common.systems.shell import require_docker


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_type(parser)


def _fetches(slug: str) -> bool:
    return bool(getattr(systems.get_class(slug), "fetches_binaries", False))


def _slugs(ctx: cli.Context) -> list[str]:
    raw = ctx.args.type
    if raw and raw.upper() == constants.TARGET_ALL:
        return [s for s in systems.all_slugs() if _fetches(s)]
    if raw and "," in raw:
        return [n.strip() for n in raw.split(",") if n.strip()]
    return [ctx.slug]


def run(ctx: cli.Context) -> int:
    slugs: list[str] = []
    for slug in _slugs(ctx):
        if _fetches(slug):
            slugs.append(slug)
        else:
            console.warn(f"{slug} has no binaries of its own — nothing to fetch")
    # Docker only when a container is in the selection: a native system's
    # archives are a download.
    if any(getattr(systems.get_class(s), "is_container", False) for s in slugs):
        require_docker()
    done: set[str] = set()
    for slug in slugs:
        systems.get(slug).fetch_bin(done)
    if not done:
        console.out("no binaries to fetch for the selected type(s)")
        return 0
    console.good(f"fetched binaries for {', '.join(slugs)}")
    return 0
