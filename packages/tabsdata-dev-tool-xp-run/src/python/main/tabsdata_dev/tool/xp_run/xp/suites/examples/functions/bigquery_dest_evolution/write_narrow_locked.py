#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery: create a SECOND target, this one under a contract.

Same narrow frame, a different table — so one run can show both outcomes side by
side: `products_evolve` ends up four columns wide, `products_locked` stays two.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


@subscriber(
    destination=BigQueryDest(tables=["`products_locked`"], if_table_exists="replace"),
    input_tables=["gen/products_v1"],
)
def write_narrow_locked(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
