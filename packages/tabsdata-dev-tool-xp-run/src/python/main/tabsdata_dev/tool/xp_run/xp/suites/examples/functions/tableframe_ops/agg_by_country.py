#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: AGGREGATION — `group_by(...).agg(...)`.

Each expression in `agg` is a REDUCTION over the group, and `alias` names the
output column. ALIAS EVERYTHING: without it the column keeps the source column's
name, so aggregating `amount` twice gives you two columns called `amount` and the
second wins.

The reductions available are the usual set — `count`, `sum`, `mean`, `min`,
`max`, `n_unique`, `first`, `last` — applied per group.

ROW-PRESERVING vs RESHAPING, THE ONE CAVEAT IN THIS SUITE
    Everything else here maps rows one-to-one or drops some, so the framework's
    system columns (provenance, versioning) travel with them. `group_by().agg()`
    BUILDS NEW ROWS and cannot preserve what it has collapsed.

    That matters at a SINK: an aggregate is a fine table for another transformer
    to read, but a `@subscriber` writing one out may fail on the system columns it
    no longer has. So aggregate freely MID-PIPELINE, and keep the LAST hop before
    a destination row-preserving.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer
from tabsdatak.tableframe.functions import col


@transformer(input_tables=["src/orders@NEW"], output_tables=["revenue_by_country"])
def agg_by_country(orders: TableFrameSpec) -> TableFrameSpec:
    return orders.group_by("country").agg(
        col("order_id").count().alias("orders"),
        col("amount").sum().alias("revenue"),
        col("amount").mean().alias("avg_order"),
        col("amount").max().alias("largest_order"),
        col("customer_id").n_unique().alias("customers"),
    )
