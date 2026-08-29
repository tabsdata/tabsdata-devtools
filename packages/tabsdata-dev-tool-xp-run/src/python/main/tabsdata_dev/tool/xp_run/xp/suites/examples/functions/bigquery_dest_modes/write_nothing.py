#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery destination: RETURNING None.

Nothing is staged and nothing is loaded — and a `replace` target is NOT emptied.
"No data this run" leaves the warehouse exactly as it was, which also means no
staging cost for a run with nothing to say.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


@subscriber(
    destination=BigQueryDest(tables=["`customers_append`"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
