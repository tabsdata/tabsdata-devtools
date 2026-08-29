#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — `trigger_by=TablesTrigger(tables=[...])`: fire on a NAMED set.

A transformer with no `trigger_by` already fires reactively on its `@NEW` inputs,
so what does this add? CONTROL OVER WHICH ONES. `input_tables` says what the
function READS; `TablesTrigger` says what it WAKES FOR, and they do not have to
be the same list.

That separation is the whole point:

    reads A@NEW, B@HEAD  +  TablesTrigger(["coll/A"])
        A is the driver, B is a lookup — a new B does NOT recompute anything.
        (`@HEAD` already implies this, so here the trigger is belt and braces.)

    reads A@NEW, B@NEW   +  TablesTrigger(["coll/A"])
        both are read fresh, but only A's arrival starts a run. Use it when B is
        updated far more often than A and you do not want a run per B.

Entries are `collection/table` references — fully qualified, because the watched
table may live in another collection entirely.

This one fires off the every-minute cron publisher, which is what makes the chain
visible: a schedule starts the publisher, the publisher's batch starts this. No
`triggers` entry in the suite descriptor for either.

`select` keeps the transform ROW-PRESERVING, which a transformer's output has to
be if a subscriber is going to sink it (see `tableframe_ops`).
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TablesTrigger, transformer
from tabsdatak.tableframe.functions import col


@transformer(
    input_tables=["scheduled/batches"],
    output_tables=["batches_checked"],
    trigger_by=TablesTrigger(tables=["scheduled/batches"]),
)
def trigger_on_named_tables(batch: TableFrameSpec) -> TableFrameSpec:
    # A tick that published nothing (the chunked frame is spent) leaves this
    # slot empty; returning None publishes no version rather than an empty one.
    if batch is None:
        return None
    return batch.select(col("id"), col("name"))
