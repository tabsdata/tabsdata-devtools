#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (an entity-container + owner) in a system.

The shared create, with ``--pgvector on|off`` (default off): on, the domain's
database gets the pgvector extension, which every postgresnative system carries.
The choice is recorded in the domain's meta (``PGVECTOR``), so ``manifest``
replays it.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli
from tabsdata_dev.common.systems.systems._common.commands import dom_create
from tabsdata_dev.common.systems.systems.postgresnative.backend import (
    PGVECTOR_OFF,
    PGVECTOR_ON,
)

OPT_PGVECTOR = "--pgvector"


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create.add_arguments(parser)
    parser.add_argument(
        OPT_PGVECTOR,
        dest="pgvector",
        choices=(PGVECTOR_ON, PGVECTOR_OFF),
        default=PGVECTOR_OFF,
        help=f"create the pgvector extension in the domain's database "
        f"(default {PGVECTOR_OFF})",
    )


def run(ctx: cli.Context) -> int:
    ctx.system.use_pgvector(ctx.args.pgvector)
    return dom_create.run(ctx)
