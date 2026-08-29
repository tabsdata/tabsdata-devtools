#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Oracle destination: RETURNING None.

The write is NOT invoked for that slot: nothing is inserted — and, importantly,
nothing is TRUNCATED either. A `replace` sink that returns `None` leaves the
target's previous contents exactly as they were, rather than emptying it.

That asymmetry is the useful part: "no data this run" never destroys what is
already there.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.oracle import OracleDest


@subscriber(
    destination=OracleDest(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
