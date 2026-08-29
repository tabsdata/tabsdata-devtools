#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery: `schema_evolution="strict"`, and what you do about it.

Handing this target the wider frame AS-IS would FAIL the write. That is the whole
value of `strict`: a target with a contract tells you upstream changed shape,
instead of silently growing columns nobody planned.

So the function CONFORMS the frame to the target — `select` the columns the table
has — which is the real answer at a strict boundary: decide explicitly what the
extra columns mean rather than letting them widen a table by accident. It also
keeps this suite green instead of demonstrating by crashing.

TO SEE THE REFUSAL: delete the `.select(...)` below and re-run. The write fails
with a schema mismatch.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


@subscriber(
    destination=BigQueryDest(
        tables=["`products_locked`"],
        if_table_exists="append",
        schema_evolution="strict",
    ),
    input_tables=["gen/products_v2"],
)
def write_wider_conformed(v2: TableFrameSpec) -> TableFrameSpec:
    return v2.select("sku", "name")
