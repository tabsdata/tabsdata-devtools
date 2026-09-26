#
# Copyright 2026 Tabsdata Inc.
#

"""Push another batch of the model's data to a redpanda domain's topics.

Kafka is append-only, so modify-data does not apply the shared delta recipe
(insert/update/delete on specific rows); instead it produces a fresh batch of the
model's rows as new JSON messages to every ``<domain>.<entity>`` topic. ``--size``
sets the batch multiplier (as in create-data); successive runs advance the seed so
models with random data vary (fixed reference models re-emit the same rows).
``--dry-run`` plans the batch without producing it and leaves the seed where it
was; ``--emit-ops FILE`` appends the batch to FILE as CDC-style JSON lines.
"""

from __future__ import annotations

import argparse
import random

from tabsdata_dev.common.systems import cli, console, constants, datagen, descriptor
from tabsdata_dev.common.systems.errors import TdxError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)
    cli.add_size(parser)
    cli.add_data_dry_run(parser)
    cli.add_emit_ops(parser)
    cli.add_latch(parser)


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    a = ctx.args
    info = ctx.info
    sysobj = ctx.system
    if not info.model:
        raise TdxError(f"domain '{ctx.name}' has no model — run create-model first")
    if a.size < 1:
        raise TdxError(f"{constants.OPT_SIZE} must be >= 1 (1 = base)")
    seed = info.seed + 1  # advance so successive batches vary (fixed models re-emit)
    n = datagen.BASE_SIZE * a.size
    tables = datagen.load_model(info.model).build_initial(
        random.Random(datagen.INITIAL_SEED + seed), n
    )
    if a.dry_run:
        _emit(ctx, tables, seed, dry_run=True)
        if console.json_mode():
            console.result({t.name: datagen.iud(insert=len(t.rows)) for t in tables})
        else:
            console.good(
                f"would push {sum(len(t.rows) for t in tables)} message(s) to "
                f"domain '{ctx.name}' -- dry run, nothing produced"
            )
        return 0
    with sysobj.data_plane_uri(info.meta) as uri:
        produced = sysobj.load_tables(uri, tables)
    counts = dict(info.entities)
    for topic, count in produced.items():
        counts[topic] = counts.get(topic, 0) + count  # kafka log appends
    descriptor.record_changes(ctx.path, counts, seed=seed)
    _emit(ctx, tables, seed, dry_run=False)
    if console.json_mode():
        report = {topic: datagen.iud(insert=n) for topic, n in produced.items()}
        console.result(report)
    else:
        console.good(
            f"pushed {sum(produced.values())} message(s) to {len(produced)} "
            f"topic(s) in domain '{ctx.name}'"
        )
    return 0


def _emit(ctx: cli.Context, tables: list, seed: int, *, dry_run: bool) -> None:
    if ctx.args.emit_ops:
        assert ctx.name is not None
        batch = [datagen.initial_changes(tables)]
        datagen.append_ops(
            ctx.args.emit_ops, ctx.name, ctx.verb, batch, dry_run=dry_run, seed=seed
        )
