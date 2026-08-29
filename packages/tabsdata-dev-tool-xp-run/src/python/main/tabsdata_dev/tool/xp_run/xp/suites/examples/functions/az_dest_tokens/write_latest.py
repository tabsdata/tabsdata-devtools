#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Azure Blob destination: NO TOKEN, the deliberate contrast.

A fixed path is not a mistake — it is the right answer when what you want is one
file that always holds the current state, overwritten on every run. Point a
dashboard or a spreadsheet at this; point a pipeline at the token-written ones.

The two styles coexist happily in one suite, which is the point: pick per sink,
not per project.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.azureblob import AzureBlobDest


@subscriber(
    destination=AzureBlobDest(paths=["current/customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_latest(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
