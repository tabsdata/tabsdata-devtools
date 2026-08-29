#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 destination: `if_table_exists="replace"`.

TRUNCATE the table, then insert. The row count is whatever this run produced,
however often it runs — the mode for a table that mirrors a source of truth.

WHEN COLUMN TYPES ARE DECIDED: only when the target is CREATED — that is, under
`replace`, or under `append` into a table that does not exist yet. Writing into
an EXISTING table uses that table's columns and types, and a frame that does not
fit fails the write. So either create the table yourself with the DDL you want,
or let the first write create it and accept the connector's type mapping
(`TYPE_MAPPING.md` in `tabsdata-conn-common-sql` is the per-database matrix).

A separate target from the append example, so both can fire off the same publish.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.db2 import Db2Dest


@subscriber(
    destination=Db2Dest(tables=["customers_replace"], if_table_exists="replace"),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
