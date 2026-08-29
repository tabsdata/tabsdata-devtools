#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Azure Blob destination: ONE FOLDER PER RUN, with both files in it.

`${EXEC_PLAN_ID}` names the whole plan a trigger started, so every sink in the
same run resolves it to the same value. Putting it in the DIRECTORY position is
therefore how you group a run's outputs: this one subscriber writes two files
that land together, and any other sink in the same plan would land beside them.

Use `${TRX_ID}` when each write must be independently identifiable, and
`${EXEC_PLAN_ID}` when what matters is which run produced a set of files.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.azureblob import AzureBlobDest


@subscriber(
    destination=AzureBlobDest(
        paths=[
            "runs/${EXEC_PLAN_ID}/customers.csv",
            "runs/${EXEC_PLAN_ID}/orders.csv",
        ],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_per_plan(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
