#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. The three tables every transform in this suite
reads.

`customers` and `customers_previous` are two SNAPSHOTS of the same entity:
customer 4 has since left, customer 5 is new, 1–3 are unchanged. That is what
gives the diff examples something real to find — a diff of two identical frames
teaches nothing.

`orders` deliberately has NO row for customer 5, which is the difference between
an inner and a left join, and repeats customers 1 and 2 so the aggregations have
groups of more than one.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "customer_id": [1, 2, 3, 4, 5],
                "name": ["Ada", "Grace", "Alan", "Edsger", "Barbara"],
                "country": ["GB", "US", "GB", "NL", "US"],
                "tier": ["gold", "gold", "silver", "silver", "bronze"],
            })),
            Data(pl.DataFrame({
                "customer_id": [1, 2, 3, 4],
                "name": ["Ada", "Grace", "Alan", "Edsger"],
                "country": ["GB", "US", "GB", "NL"],
                "tier": ["gold", "gold", "silver", "silver"],
            })),
            Data(pl.DataFrame({
                "order_id": [100, 101, 102, 103, 104, 105],
                "customer_id": [1, 2, 1, 3, 4, 2],
                "country": ["GB", "US", "GB", "GB", "NL", "US"],
                "amount": [19.99, 250.00, 7.50, 1300.00, 42.00, 88.00],
                "status": ["shipped", "shipped", "cancelled", "pending",
                           "shipped", "shipped"],
            })),
        ]
    ),
    output_tables=["customers", "customers_previous", "orders"],
)
def generate_tables(
    customers: TableFrameSpec,
    previous: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (customers, previous, orders)
