#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 destination: TWO FILES from one subscriber.

Two paths, two input tables, two returned frames — all POSITIONAL. Use one
subscriber when the files belong together (they are written in the same
transaction); use two when they do not, so one failing does not hold up the other.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.s3 import S3Dest


@subscriber(
    destination=S3Dest(
        paths=["customers_multi.csv", "orders_multi.csv"],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_files(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
