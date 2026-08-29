#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: a LEFT JOIN, which keeps the unmatched rows.

Every customer survives, including customer 5 — who has no orders — whose order
columns come back NULL. That is the whole difference from the inner join, and it
is the one to reach for when the LEFT side is the population you are reporting
on: an inner join here would silently under-count customers.

`how` also takes `"right"`, `"full"`, `"outer"`, `"cross"`, `"semi"` and
`"anti"`. The last two are set operations rather than joins — see the `diff_*`
functions in this suite.

A LEFT JOIN CAN GROW THE ROW COUNT. If the right side has several matches per
key (as `orders` does for customers 1 and 2), each one produces a row. When you
wanted "customers, annotated", aggregate the right side FIRST and join the
aggregate — `agg_top_customers.py` shows that shape.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["src/customers@NEW", "src/orders@HEAD"],
    output_tables=["customers_with_orders"],
)
def join_left(customers: TableFrameSpec, orders: TableFrameSpec) -> TableFrameSpec:
    return customers.join(
        orders.select("order_id", "customer_id", "amount"),
        on="customer_id",
        how="left",
    )
