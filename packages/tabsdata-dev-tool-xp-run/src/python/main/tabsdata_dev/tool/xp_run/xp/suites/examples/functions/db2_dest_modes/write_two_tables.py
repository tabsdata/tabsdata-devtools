#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 destination: TWO TABLES IN ONE WRITE, atomically.

Two names, two input tables, two returned frames — positional. `transactional`
defaults to `True` (spelled out here), which wraps EVERY table's write in one
transaction: either both targets are written or neither is.

That is the reason to put related targets in one subscriber. Two subscribers
would write independently, and a failure between them would leave the pair
inconsistent.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.db2 import Db2Dest


@subscriber(
    destination=Db2Dest(
        tables=["customers_both", "orders_both"],
        if_table_exists="replace",
        transactional=True,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_tables(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
