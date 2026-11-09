#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (a topic prefix) in a redpanda system.

The shared create, with ``--registry on|off`` (default off): on, the Avro and
Protobuf messages the domain's model names are produced in the Confluent
schema-registry wire format, each schema registered with the system's registry
(``redpanda.wire``). The choice is recorded in the domain's meta
(``REGISTRY``), so ``manifest`` replays it. JSON messages are never framed.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli
from tabsdata_dev.common.systems.systems._common.commands import dom_create
from tabsdata_dev.common.systems.systems.redpanda import wire


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create.add_arguments(parser)
    parser.add_argument(
        wire.OPT_REGISTRY,
        dest="registry",
        choices=(wire.REGISTRY_ON, wire.REGISTRY_OFF),
        default=wire.REGISTRY_OFF,
        help="frame the model's Avro and Protobuf messages for the schema "
        f"registry (default {wire.REGISTRY_OFF}: plain, the schema given to the "
        "consumer)",
    )


def run(ctx: cli.Context) -> int:
    ctx.system.use_registry(ctx.args.registry)
    return dom_create.run(ctx)
