#
# Copyright 2026 Tabsdata Inc.
#

"""Generate and load deterministic initial data for the domain's model.

``--dry-run`` plans the load without loading it: the system and the
descriptor are left alone, so it needs no ``--force`` on a domain that already
has data. ``--emit-ops FILE`` appends the load's operations to FILE as
CDC-style JSON lines, after the load or in place of it.
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
    cli.add_force(parser)
    cli.add_data_dry_run(parser)
    cli.add_emit_ops(parser)
    cli.add_latch(parser)


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    a = ctx.args
    info = ctx.info
    sysobj = ctx.system
    model = info.model
    if not model:
        raise TdxError(f"domain '{ctx.name}' has no model — run create-model first")
    if a.size < 1:
        raise TdxError(f"{constants.OPT_SIZE} must be >= 1 (1 = base)")
    if info.data and not a.force and not a.dry_run:
        raise TdxError(
            f"domain '{ctx.name}' already has data (size x{info.data}); "
            f"use {constants.OPT_FORCE} to reload"
        )
    model_obj = datagen.load_model(model)
    n = datagen.BASE_SIZE * a.size
    tables = model_obj.build_initial(random.Random(datagen.INITIAL_SEED), n)
    if a.dry_run:
        return _dry_run(ctx, tables)
    reload = bool(a.force or info.data)
    if reload:
        sysobj.install_schema(info.meta, model, force=True)  # reload = drop + recreate
    with sysobj.data_plane_uri(info.meta) as uri:
        entities = sysobj.load_tables(uri, tables)
    recorded = dict(entities)
    if datagen.SENTINEL_ENTITY in info.entities:
        # Never loaded here, so its count is carried: rows sentinel-data wrote
        # after create-model are still there, unless this load dropped them.
        kept = 0 if reload else info.entities[datagen.SENTINEL_ENTITY]
        recorded[datagen.SENTINEL_ENTITY] = kept
    descriptor.record_data(ctx.path, str(a.size), recorded)
    _emit(ctx, tables, dry_run=False)
    rows = sum(len(t.rows) for t in tables)
    if console.json_mode():
        report = {name: datagen.iud(insert=count) for name, count in entities.items()}
        console.result(report)
    else:
        console.good(f"loaded {rows} rows (size x{a.size}) into domain '{ctx.name}'")
    return 0


def _emit(ctx: cli.Context, tables: list, *, dry_run: bool) -> None:
    if ctx.args.emit_ops:
        assert ctx.name is not None
        batch = [datagen.initial_changes(tables)]
        datagen.append_ops(
            ctx.args.emit_ops, ctx.name, ctx.verb, batch, dry_run=dry_run
        )


def _dry_run(ctx: cli.Context, tables: list) -> int:
    _emit(ctx, tables, dry_run=True)
    if console.json_mode():
        console.result({t.name: datagen.iud(insert=len(t.rows)) for t in tables})
    else:
        rows = sum(len(t.rows) for t in tables)
        console.good(
            f"would load {rows} rows (size x{ctx.args.size}) into domain "
            f"'{ctx.name}' -- dry run, nothing loaded"
        )
    return 0
