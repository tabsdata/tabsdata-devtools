#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks destination: `if_table_exists="replace"`.

Overwrite the table: the row count is whatever this run produced, however often
it runs. The mode for a mirror of a source of truth.

Column types are decided ONLY when the target is created — under `replace`, or
under `append` into a missing table. Writing into an existing table uses that
table's types, and a frame that does not fit fails the write.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(tables=["customers_replace"], if_table_exists="replace"),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
