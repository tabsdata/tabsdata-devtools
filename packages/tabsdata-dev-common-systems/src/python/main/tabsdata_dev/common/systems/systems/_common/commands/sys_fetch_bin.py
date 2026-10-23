#
# Copyright 2026 Tabsdata Inc.
#

"""Fetch the docker image(s) a system needs: pulled from their registry, or
built here for a system whose image is not published.

``--type ALL`` pulls the images for every container system, ``--type a,b`` for
the listed ones; the pulled images are de-duplicated across the selection.

A system that runs no container has nothing to pull. Naming one is a warning and
a skip, never a failure, so pre-pulling everything in one go stays a single
command whatever the selection holds.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, constants, systems
from tabsdata_dev.common.systems.shell import require_docker


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_type(parser)


def _slugs(ctx: cli.Context) -> list[str]:
    raw = ctx.args.type
    if raw and raw.upper() == constants.TARGET_ALL:
        return [
            s
            for s in systems.all_slugs()
            if getattr(systems.get_class(s), "is_container", False)
        ]
    if raw and "," in raw:
        return [n.strip() for n in raw.split(",") if n.strip()]
    return [ctx.slug]


def run(ctx: cli.Context) -> int:
    require_docker()
    done: set[str] = set()
    slugs: list[str] = []
    for slug in _slugs(ctx):
        if not getattr(systems.get_class(slug), "is_container", False):
            console.warn(f"{slug} runs no container — nothing to fetch")
            continue
        slugs.append(slug)
        systems.get(slug).fetch_images(done)
    if not done:
        console.out("no docker images to fetch for the selected type(s)")
        return 0
    console.good(f"fetched images for {', '.join(slugs)}")
    return 0
