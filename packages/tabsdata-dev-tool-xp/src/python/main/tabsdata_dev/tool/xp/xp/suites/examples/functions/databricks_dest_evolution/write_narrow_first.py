#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks: CREATE the target from the narrow frame.

`replace` rather than `append`, so the example is REPEATABLE: it recreates the
two-column table from scratch, and a second run of the project starts from the
same place instead of appending to an already-evolved table.

The evolution happens in `write_wider_evolving.py`, which must be `append` —
a `replace` there would recreate the table wide and there would be nothing to
observe.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(tables=["products_evolve"], if_table_exists="replace"),
    input_tables=["gen/products_v1"],
)
def write_narrow_first(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
