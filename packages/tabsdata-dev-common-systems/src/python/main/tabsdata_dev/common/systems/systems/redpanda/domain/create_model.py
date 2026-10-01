#
# Copyright 2026 Tabsdata Inc.
#

"""Create a model's topics in a redpanda domain, one per entity.

The shared create-model, with ``--up-to-partitions N``: the model's i-th entity
gets ``i mod N + 1`` partitions, so the topics differ from one another (1, the
default, is one partition each). The counts are recorded in the domain's meta
(``PARTITIONS``), and a create-data reload creates the topics again from them.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, datagen, descriptor
from tabsdata_dev.common.systems.systems._common.commands import dom_create_model
from tabsdata_dev.common.systems.systems.redpanda import shape


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create_model.add_arguments(parser)
    parser.add_argument(
        shape.OPT_UP_TO_PARTITIONS,
        dest="up_to_partitions",
        type=int,
        default=1,
        metavar="N",
        help="the most partitions a topic gets: the i-th entity gets i mod N + 1 "
        "(default 1, one each)",
    )


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    a = ctx.args
    counts = shape.plan_partitions(
        datagen.entities_of(a.model) if a.model else [], a.up_to_partitions
    )
    # In memory for the install the shared command runs; written to the
    # descriptor only once it succeeded, so a refused create-model changes nothing.
    ctx.info.meta[shape.META_PARTITIONS] = shape.encode_partitions(counts)
    rc = dom_create_model.run(ctx)
    if rc == 0:
        info = descriptor.load(ctx.path)
        assert isinstance(info, descriptor.DomainInfo)
        info.meta[shape.META_PARTITIONS] = ctx.info.meta[shape.META_PARTITIONS]
        descriptor.save(info, ctx.path)
    return rc
