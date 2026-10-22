#
# Copyright 2026 Tabsdata Inc.
#

"""Add a row to the domain's xp_sentinel entity: the key, stamped now.

A test writes a sentinel to mark a point in its run and waits for that key to
show up downstream. It needs only the model: the entity is created with every
other one and create-data never fills it. The time is UTC, to the second, and
naive -- the column is a plain timestamp on every backend. On a SQL backend the
key is the primary key, so writing the same one twice is refused there; the
file and kafka backends append it again. ``--dry-run`` stamps the row and
writes nothing; ``--emit-ops FILE`` appends it to FILE as a CDC-style JSON line.
"""

from __future__ import annotations

import argparse
from datetime import UTC, datetime

from tabsdata_dev.common.systems import cli, console, constants, datagen, descriptor
from tabsdata_dev.common.systems.datagen import Change, OpKind
from tabsdata_dev.common.systems.errors import TdxError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)
    parser.add_argument(
        constants.OPT_KEY,
        required=True,
        metavar="KEY",
        help="the sentinel's key (at most 255 characters)",
    )
    cli.add_data_dry_run(parser)
    cli.add_emit_ops(parser)
    cli.add_latch(parser)


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    info = ctx.info
    key = ctx.args.key
    if not info.model:
        raise TdxError(f"domain '{ctx.name}' has no model — run create-model first")
    if datagen.SENTINEL_ENTITY not in datagen.entities_of(info.model):
        raise TdxError(f"model '{info.model}' has no {datagen.SENTINEL_ENTITY} entity")
    if not key or len(key) > 255:
        raise TdxError(f"{constants.OPT_KEY} must be 1 to 255 characters")
    stamp = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    row = {"sentinel_key": key, "sentinel_ts": stamp}
    change = Change(
        OpKind.INSERT, datagen.SENTINEL_ENTITY, datagen.SENTINEL_COLUMNS, row=row
    )
    dry_run = ctx.args.dry_run
    if not dry_run:
        with ctx.system.data_plane_uri(info.meta) as uri:
            entities = ctx.system.apply_changes(
                uri, [[change]], info.entities, label=constants.V_SENTINEL_DATA
            )
        descriptor.record_changes(ctx.path, entities)
    if ctx.args.emit_ops:
        assert ctx.name is not None
        datagen.append_ops(
            ctx.args.emit_ops, ctx.name, ctx.verb, [[change]], dry_run=dry_run
        )
    if console.json_mode():
        console.result(
            {"entity": change.table, **row, "sentinel_ts": stamp.isoformat()}
        )
    else:
        done = " -- dry run, nothing written" if dry_run else ""
        console.good(
            f"sentinel '{key}' at {stamp.isoformat()} UTC in domain '{ctx.name}'{done}"
        )
    return 0
