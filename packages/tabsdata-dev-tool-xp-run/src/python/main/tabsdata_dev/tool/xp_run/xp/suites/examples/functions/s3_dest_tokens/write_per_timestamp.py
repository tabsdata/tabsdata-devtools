#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 destination: A CHRONOLOGICAL layout.

`${EXEC_PLAN_TS}` is the execution plan's timestamp, so it sorts correctly in a
plain listing — which the opaque ids do not. Reach for it whenever a human, a
`ls`, or a lexicographic key range has to find "the latest".
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.s3 import S3Dest


@subscriber(
    destination=S3Dest(paths=["daily/${EXEC_PLAN_TS}/customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_per_timestamp(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
