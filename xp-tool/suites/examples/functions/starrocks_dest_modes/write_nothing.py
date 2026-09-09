#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — StarRocks destination: RETURNING None.

Nothing is staged and nothing is loaded — and the `replace` target is NOT
truncated. On a connector whose replace mode throws away a seeded table, that
asymmetry is worth being sure of: a run with no data cannot empty the target.

NOT EXERCISED HERE: `schema_evolution="iceberg"`. StarRocks loads via
`INSERT ... SELECT * FROM FILES(...)` and does not pre-ALTER the target on that
path, so a widened frame fails with a column-count mismatch rather than adding
the column — unlike ClickHouse, whose iceberg path does add it. The field exists;
the load path cannot yet use it.
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
