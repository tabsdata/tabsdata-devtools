#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — SQL Server destination: `transactional=False`, and `dest_cfg`.

Commits per table instead of wrapping the write in one transaction: faster, and
it holds fewer locks for less time — at the price of partial results when one
table fails.

`dest_cfg` tunes the write itself. `tabsdata.sql.chunk_size` is the knob that
matters for a big load: it sets how many rows go per round trip, trading memory
for fewer, larger statements.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mssql import MSSQLDest


@subscriber(
    destination=MSSQLDest(
        tables=["orders_fast"],
        if_table_exists="replace",
        transactional=False,
        dest_cfg={"tabsdata.sql.chunk_size": 50000},
    ),
    input_tables=["gen/orders"],
)
def write_without_transaction(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
