#
# Copyright 2026 Tabsdata Inc.
#

"""Push another batch of the model's data to a redpanda domain's topics.

Kafka is append-only, so modify-data does not apply the shared delta recipe
(insert/update/delete on specific rows); instead it produces a fresh batch of the
model's rows as new messages (in each topic's format) to every ``<domain>.<entity>`` topic. ``--size``
sets the batch multiplier (as in create-data); successive runs advance the seed so
models with random data vary (fixed reference models re-emit the same rows).
``--dry-run`` plans the batch without producing it and leaves the seed where it
was; ``--emit-ops FILE`` appends the batch to FILE as CDC-style JSON lines.
``--entity A,B`` pushes to those topics alone and ``--schema-changes`` varies
the messages' shape, as create-data's do (``redpanda.shape``).

A model with ``kafka_recipe`` (bronze) is not re-emitted: its next batch is the
INSERTs its recipe plans -- each entity's per-set rows times ``--size``, at the
next seed -- continuing what the seed and the earlier runs produced (new keys,
CDC rows for live keys, the next period), and the run is kept in the
descriptor for the next one to continue from. A table the domain's message
format cannot hold is left out of either, and said.
"""

from __future__ import annotations

import argparse
import random

from tabsdata_dev.common.systems import (
    cli,
    console,
    constants,
    datagen,
    descriptor,
    emit,
)
from tabsdata_dev.common.systems.datagen import ChangeSpec, OpSelector
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems.redpanda import shape, wire
from tabsdata_dev.common.systems.systems.redpanda.domain import create_data


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)
    cli.add_size(parser)
    create_data.add_entity(parser)
    create_data.add_schema_changes(parser)
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
    model_obj = datagen.load_model(info.model)
    spec = None
    if model_obj.kafka_recipe:
        spec, tables = _recipe(ctx, model_obj, seed)
    else:
        n = datagen.BASE_SIZE * a.size
        tables = model_obj.build_initial(random.Random(datagen.INITIAL_SEED + seed), n)
        tables = shape.select_tables(tables, a.entity)
    formats = wire.domain_formats(info.meta, [t.name for t in tables])
    tables = create_data.leave_out(tables, formats)
    kinds = shape.parse_kinds(a.schema_changes)
    shape.refuse_schema_changes(tables, kinds, formats)
    tables = shape.vary_tables(tables, kinds)
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
    change = spec.to_dict() if spec is not None and model_obj.replays else None
    descriptor.record_changes(ctx.path, counts, seed=seed, change=change)
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


def _recipe(
    ctx: cli.Context, model_obj: datagen.Model, seed: int
) -> tuple[ChangeSpec, list]:
    """The INSERTs a recipe model's next run produces, and its spec: each
    entity's per-set rows times ``--size`` -- a table the domain's format
    cannot hold left out of the plan, so the state the next run continues has
    nothing no topic got."""
    a = ctx.args
    info = ctx.info
    assert isinstance(info, descriptor.DomainInfo)
    if not info.data:
        raise TdxError(
            f"domain '{ctx.name}' has no data -- its model's changes continue its "
            f"seed: run create-data first"
        )
    by = {e.table: e for e in model_obj.entities}
    if not a.entity or a.entity.strip().upper() == constants.ENTITY_ALL:
        names = list(by)
    else:
        names = [n.strip() for n in a.entity.split(",") if n.strip()]
        unknown = [n for n in names if n not in by]
        if unknown or not names:
            raise TdxError(
                f"{constants.OPT_ENTITY}: unknown entit"
                f"{'y' if len(unknown) == 1 else 'ies'} {', '.join(unknown)} "
                f"(this model changes: {', '.join(by)})"
            )
    formats = wire.domain_formats(info.meta, names)
    left = [
        n
        for n in names
        if wire.unencodable(formats.get(n, datagen.MESSAGE_JSON), n, by[n].columns)
    ]
    names = [n for n in by if n in names and n not in left]
    if not names:
        raise TdxError(
            f"modify-data: no entity left to change -- {', '.join(left)} cannot be "
            f"{wire.default_format(info.meta)} messages"
        )
    spec = ChangeSpec(
        entities=names,
        ops=OpSelector.INSERT,
        sets=1,
        rows_per_entity={n: by[n].rows_per_set * a.size for n in names},
        seed=seed,
        insert_base=seed * datagen.FIXED_SEED_INSERT_STRIDE,
    )
    history = (
        [ChangeSpec.from_dict(d) for d in info.changes] if model_obj.replays else []
    )
    txns = datagen.plan(
        model_obj,
        spec,
        datagen.seeded_rows(info.seeded or info.entities),
        size=datagen.size_of(info.data),
        history=history,
        verbs=ctx.system.change_verbs,
    )
    tables = datagen.tables_of(txns)
    # The left-out tables, still named, so the run says why they got nothing.
    tables += [emit.Table(n, by[n].columns, []) for n in left]
    return spec, tables


def _emit(ctx: cli.Context, tables: list, seed: int, *, dry_run: bool) -> None:
    if ctx.args.emit_ops:
        assert ctx.name is not None
        batch = [datagen.initial_changes(tables)]
        datagen.append_ops(
            ctx.args.emit_ops, ctx.name, ctx.verb, batch, dry_run=dry_run, seed=seed
        )
