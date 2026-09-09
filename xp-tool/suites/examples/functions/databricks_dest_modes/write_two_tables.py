#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks destination: TWO TABLES from one subscriber.

Two names, two input tables, two returned frames — positional. Each is staged and
loaded in turn, so grouping them here mostly buys you one function to schedule and
one place to fail, rather than the atomicity a transactional SQL destination gives.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["customers_both", "orders_both"],
        if_table_exists="replace",
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_tables(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
