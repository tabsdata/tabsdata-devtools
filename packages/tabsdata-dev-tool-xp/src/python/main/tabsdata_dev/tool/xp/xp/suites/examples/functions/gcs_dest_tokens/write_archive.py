#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — GCS destination: CHRONOLOGICAL **AND** UNIQUE.

Tokens compose, and more than one may appear in a path. `${EXEC_PLAN_TS}` as the
directory makes the archive browsable in time order; `${TRX_ID}` in the filename
guarantees two writes never collide inside one of those directories. This is the
belt-and-braces landing-zone layout.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.gcs import GCSDest


@subscriber(
    destination=GCSDest(paths=["archive/${EXEC_PLAN_TS}/orders_${TRX_ID}.parquet"]),
    input_tables=["gen/orders"],
)
def write_archive(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
