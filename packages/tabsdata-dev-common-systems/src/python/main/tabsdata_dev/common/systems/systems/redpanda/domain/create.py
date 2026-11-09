#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (a topic prefix) in a redpanda system.

The shared create, with ``--registry on|off`` (default off): on, the Avro and
Protobuf messages the domain's model names are produced in the Confluent
schema-registry wire format, each schema registered with the system's registry
(``redpanda.wire``). The choice is recorded in the domain's meta
(``REGISTRY``), so ``manifest`` replays it. JSON messages are never framed.

``--message-format json|avro|protobuf`` (default json) is the format of every
entity the domain's model does not name in its ``message_formats``: one domain
per format, so a suite reads every table of a model as Avro, or as Protobuf.
Recorded as ``MESSAGE_FORMAT`` and replayed by ``manifest`` too.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, datagen
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
    parser.add_argument(
        wire.OPT_MESSAGE_FORMAT,
        dest="message_format",
        choices=datagen.MESSAGE_FORMATS,
        default=datagen.MESSAGE_JSON,
        help="the format of every entity's messages the model does not name "
        f"(default {datagen.MESSAGE_JSON}); a table whose names the format cannot "
        "hold gets no messages, and the run says so",
    )


def run(ctx: cli.Context) -> int:
    ctx.system.use_registry(ctx.args.registry)
    ctx.system.use_message_format(ctx.args.message_format)
    return dom_create.run(ctx)
