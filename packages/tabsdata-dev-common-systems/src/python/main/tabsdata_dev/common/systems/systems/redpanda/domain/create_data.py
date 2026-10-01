#
# Copyright 2026 Tabsdata Inc.
#

"""Produce the model's deterministic initial data to a redpanda domain's topics.

The shared create-data, with two choices of its own (see ``redpanda.shape``):
``--entity A,B`` produces to those topics alone, leaving the others empty, and
``--schema-changes [add,drop,retype|ALL]`` varies the shape of the messages, as
it varies the trail ``--emit-ops`` writes.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, constants
from tabsdata_dev.common.systems.systems._common.commands import dom_create_data
from tabsdata_dev.common.systems.systems.redpanda import shape


def add_entity(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        constants.OPT_ENTITY,
        default=constants.ENTITY_ALL,
        metavar="NAME,NAME|ALL",
        help="the entities whose topics get messages; every other topic gets "
        "none (default ALL)",
    )


def add_schema_changes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        shape.OPT_SCHEMA_CHANGES,
        nargs="?",
        const=constants.ENTITY_ALL,
        default=None,
        metavar="KIND,KIND|ALL",
        help="vary the messages' shape, row by row: add (an extra xp_extra "
        "field), drop (the last field left out), retype (the first field "
        "another JSON type); alone, every kind (default: none)",
    )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create_data.add_arguments(parser)
    add_entity(parser)
    add_schema_changes(parser)


def run(ctx: cli.Context) -> int:
    kinds = shape.parse_kinds(ctx.args.schema_changes)
    entity = ctx.args.entity
    return dom_create_data.run(
        ctx,
        prepare=lambda tables: shape.vary_tables(
            shape.select_tables(tables, entity), kinds
        ),
    )
