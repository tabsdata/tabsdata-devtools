#
# Copyright 2026 Tabsdata Inc.
#

"""Apply deterministic changes to a domain's data (Insert / Update / Delete / Mix).

``--entity ALL`` applies each model entity's per-set row count across ``--sets``
transactions; ``--entity NAME`` applies ``--sets`` rows to that one entity;
``--entity A,B,...`` is ALL narrowed to those -- how a run changes every table
but one, which then sees no change for as long as the runs leave it out.
``--seed N`` is reproducible; ``--seed AUTO`` continues from the last seed (last
+ 1). Insert ordinals derive from the seed, so the same op/set/seed sequence is
repeatable.

``--trx-mode`` says how the transactions are applied on a SQL system: ``serial``
(one at a time), ``interleaved`` (up to ``--trx-concurrency`` open at once, a
statement from each in turn, each committing after its last), ``nested`` (each
begun inside the one before it and committed inside it too) or ``mix`` (groups
of ``--trx-concurrency``, each the next of those three) -- see ``trx``. The
schedule is as deterministic as the plan, and the report says it.

``--dry-run`` plans the operations without applying them. Neither the system
nor the descriptor is touched, so ``--seed AUTO`` does not advance and the same
dry run repeats what the next real run would do. ``--emit-ops FILE`` appends
the operations to FILE as CDC-style JSON lines, once applied or as planned, in
the order the transactions commit.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import (
    cli,
    console,
    constants,
    datagen,
    descriptor,
    trx,
)
from tabsdata_dev.common.systems.datagen import ChangeSpec, OpKind, OpSelector
from tabsdata_dev.common.systems.errors import TdxError

_OPS = {
    "insert": OpSelector.INSERT,
    "update": OpSelector.UPDATE,
    "delete": OpSelector.DELETE,
    "mix": OpSelector.MIX,
}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)
    parser.add_argument(
        constants.OPT_ENTITY,
        default=constants.ENTITY_ALL,
        metavar="NAME[,NAME...]|ALL",
        help="entity to change, a comma list of them, or ALL (default ALL); a "
        "list takes each entity's per-set rows, as ALL does",
    )
    parser.add_argument(
        constants.OPT_SETS,
        type=int,
        default=1,
        metavar="COUNT",
        help="number of change sets/transactions; for a single --entity, the row "
        "count (default 1)",
    )
    parser.add_argument(
        constants.OPT_OPS,
        default="Mix",
        metavar="OP",
        help="Insert | Update | Delete | Mix (default Mix)",
    )
    parser.add_argument(
        constants.OPT_SEED,
        default=constants.SEED_AUTO,
        metavar="N|AUTO",
        help="seed number, or AUTO to continue from the last (default AUTO)",
    )
    cli.add_trx_mode(parser)
    cli.add_trx_concurrency(parser)
    cli.add_data_dry_run(parser)
    cli.add_emit_ops(parser)
    cli.add_latch(parser)


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    a = ctx.args
    info = ctx.info
    sysobj = ctx.system
    json_mode = console.json_mode()
    model = info.model
    if not model:
        raise TdxError(
            f"domain '{ctx.name}' has no model — create-model + create-data first"
        )
    if not info.data:
        raise TdxError(f"domain '{ctx.name}' has no data — run create-data first")

    ops = _OPS.get(a.ops.strip().lower())
    if ops is None:
        raise TdxError(
            f"{constants.OPT_OPS} must be Insert|Update|Delete|Mix (got: {a.ops})"
        )
    mode = trx.parse_mode(a.trx_mode)
    # Read the flag only when it matters: serial is every backend's.
    if mode is not trx.TrxMode.SERIAL and not sysobj.supports_trx_modes:
        raise TdxError(
            f"system type '{ctx.slug}' applies {ctx.verb} serially only "
            f"({constants.OPT_TRX_MODE} {trx.TrxMode.SERIAL.value}): its changes "
            f"are not transactions it can interleave"
        )

    model_obj = datagen.load_model(model)
    by = {e.table: e for e in model_obj.entities}
    counts = info.entities

    if a.entity.upper() == constants.ENTITY_ALL:
        entities = [e.table for e in model_obj.entities]
        rows_per_entity = {e.table: e.rows_per_set for e in model_obj.entities}
        if not entities:
            raise TdxError(
                f"model '{model}' has no entities that modify-data can change "
                f"(all are fixed — see 'tdd domain models')"
            )
        fixed = [
            t
            for t in datagen.entities_of(model)
            if t not in by and t != datagen.SENTINEL_ENTITY
        ]
        if fixed and not json_mode:
            console.out(f"no modify-data support (skipped): {', '.join(fixed)}")
    else:
        names = list(dict.fromkeys(n.strip() for n in a.entity.split(",") if n.strip()))
        if not names:
            raise TdxError(
                f"{constants.OPT_ENTITY} names no entity (got: {a.entity!r})"
            )
        for ent in names:
            if ent not in by:
                raise TdxError(
                    f"unknown entity '{ent}' "
                    f"(this model changes: {', '.join(by) or 'none'})"
                )
            verbs = datagen.verbs_on(sysobj, by[ent])
            if ops is not OpSelector.MIX and OpKind(ops.value) not in verbs:
                supported = ", ".join(k.value for k in verbs) or "nothing"
                where = f" on a {ctx.slug} domain" if verbs != by[ent].supports else ""
                raise TdxError(
                    f"entity '{ent}' does not support {ops.value}{where} "
                    f"(supports: {supported})"
                )
        # Model order, parents first, whatever order they were named in.
        entities = [e.table for e in model_obj.entities if e.table in names]
        if len(entities) == 1:
            rows_per_entity = {entities[0]: 1}  # one entity: --sets is the row count
        else:
            rows_per_entity = {t: by[t].rows_per_set for t in entities}

    auto = str(a.seed).strip().upper() == constants.SEED_AUTO
    if auto:
        seed = info.seed + 1
    else:
        try:
            seed = int(a.seed)
        except ValueError:
            raise TdxError(
                f"{constants.OPT_SEED} must be a number or AUTO (got: {a.seed})"
            )
    # Inserts derive from the seed's own block, so auto and a fixed seed mint
    # identical rows and the seed sequence alone makes a run repeatable.
    insert_base = seed * datagen.FIXED_SEED_INSERT_STRIDE

    spec = ChangeSpec(
        entities=entities,
        ops=ops,
        sets=a.sets,
        rows_per_entity=rows_per_entity,
        seed=seed,
        insert_base=insert_base,
    )
    # Targets are bounded by what create-data loaded, not by today's counts:
    # `target` addresses seeded rows. A descriptor from before `seeded` was
    # recorded falls back to its current counts. A replaying model is handed
    # the runs applied since the load, which its state is rebuilt from.
    history = (
        [ChangeSpec.from_dict(d) for d in info.changes] if model_obj.replays else []
    )
    txns = datagen.plan(
        model_obj,
        spec,
        datagen.seeded_rows(info.seeded or counts),
        size=datagen.size_of(info.data),
        history=history,
        verbs=lambda e: datagen.verbs_on(sysobj, e),
    )
    # A file domain stages a snapshot's whole state, not the rows it changed.
    restage: dict = {}
    if datagen.restages_snapshots(sysobj):
        snapshots = {c.table for t in txns for c in t if by[c.table].snapshot}
        restage = model_obj.restage(snapshots) if snapshots else {}
    concurrency = trx.parse_concurrency(a.trx_concurrency)
    schedule = trx.schedule([len(t) for t in txns], mode, concurrency)
    if mode is not trx.TrxMode.SERIAL:
        clash = trx.contention(txns)
        if clash:
            table, key = clash[0]
            raise TdxError(
                f"{mode.value} transactions would contend for a row: {table} {key} "
                f"is updated or deleted by more than one transaction of this run "
                f"(more changes than the table has seeded rows left) -- fewer "
                f"{constants.OPT_SETS}, or {constants.OPT_TRX_MODE} "
                f"{trx.TrxMode.SERIAL.value}"
            )
    new_entities: dict[str, int] = {}
    if not a.dry_run:
        with sysobj.data_plane_uri(info.meta) as uri:
            extra = {"restage": restage} if restage else {}
            new_entities = sysobj.apply_changes(
                uri, txns, counts, schedule=schedule, **extra
            )
        descriptor.record_changes(
            ctx.path,
            new_entities,
            seed=seed if auto else None,
            change=spec.to_dict() if model_obj.replays else None,
        )
    if a.emit_ops:
        assert ctx.name is not None
        datagen.append_ops(
            a.emit_ops,
            ctx.name,
            ctx.verb,
            txns,
            dry_run=a.dry_run,
            seed=seed,
            trx_mode=mode.value,
            commit_order=schedule.commit_order,
        )
    applied = len(txns)
    report = _report(schedule, datagen.op_counts(txns), new_entities)
    if json_mode:
        console.result(report)
    else:
        if a.dry_run:
            console.good(
                f"would apply {applied} change set(s) [{ops.value}] seed={seed} "
                f"trx={schedule.label} to domain '{ctx.name}' -- dry run, "
                f"nothing applied"
            )
        else:
            console.good(
                f"applied {applied} change set(s) [{ops.value}] seed={seed} "
                f"trx={schedule.label} to domain '{ctx.name}'"
            )
        for line in datagen.iud_lines(report["entities"]):
            console.out(line)
    return 0


def _report(
    schedule: trx.Schedule,
    summary: dict[str, dict[OpKind, int]],
    rows: dict[str, int],
) -> dict:
    """The run's report: how the transactions were applied, and what each
    entity got -- the shape create-data reports too."""
    return {
        "trx_mode": schedule.mode.value,
        "transactions": schedule.transactions,
        "trx_concurrency": schedule.concurrency,
        "entities": {
            table: datagen.iud(
                insert=per[OpKind.INSERT],
                update=per[OpKind.UPDATE],
                delete=per[OpKind.DELETE],
                rows=rows.get(table),
            )
            for table, per in summary.items()
        },
    }
