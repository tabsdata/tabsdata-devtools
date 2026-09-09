#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. Writes the one parquet file the multi-path
readers pair with the CSVs.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.gcs import GCSDest


@subscriber(
    destination=GCSDest(paths=["orders.parquet"], format=DestFileFormat.PARQUET),
    input_tables=["gen/orders"],
)
def stage_parquet_file(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
