#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — StarRocks destination: RETURNING None.

Nothing is staged and nothing is loaded — and the `replace` target is NOT
truncated. On a connector whose replace mode throws away a seeded table, that
asymmetry is worth being sure of: a run with no data cannot empty the target.

NOT EXERCISED HERE: `schema_evolution="update"`, which ALTERs the target
before the load — a new column added, a type widened (a StarRocks job the write
waits for). These targets are the seeded world tables, which the example keeps
as the model made them; the schema-evolution suites cover it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["gen/world_city"],
)
def write_nothing(city: TableFrameSpec) -> TableFrameSpec:
    return None
