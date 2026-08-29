#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: THE REAL SHAPE — aggregate, join back, sort, take N.

Almost no useful aggregate is the last step. The pattern is nearly always:

    1. AGGREGATE the fact table down to one row per key,
    2. JOIN that result back to a DIMENSION for its labels,
    3. SORT and take the top N.

Doing it in that order is what keeps it cheap: the join happens on the small,
already-reduced frame rather than on every order. Joining first and aggregating
after gives the same answer and moves far more data.

`sort(...).head(n)` is the top-N idiom. `unique(subset=[...])` is the dedupe one
(see `union_and_dedupe.py`).

This function reads TWO tables — `orders@NEW` drives it, `customers@HEAD` is the
lookup — and produces a reshaped table, so the caveat in `agg_by_country.py`
applies: fine for another transformer to read, not the shape to hand straight to
a subscriber.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer
from tabsdatak.tableframe.functions import col


@transformer(
    input_tables=["src/orders@NEW", "src/customers@HEAD"],
    output_tables=["top_customers"],
)
def agg_top_customers(
    orders: TableFrameSpec,
    customers: TableFrameSpec,
) -> TableFrameSpec:
    totals = orders.group_by("customer_id").agg(
        col("amount").sum().alias("total_spend"),
        col("order_id").count().alias("orders"),
    )
    return (
        totals.join(
            customers.select("customer_id", "name", "tier"),
            on="customer_id",
            how="left",
        )
        .sort("total_spend", descending=True)
        .head(3)
    )
