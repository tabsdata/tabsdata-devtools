#
# Copyright 2026 Tabsdata Inc.
#

"""caps_starrocks — StarRocks bulk dest write modes. Input comes from the dev datagen
``caps_input`` collection (same as every other capability suite), so the data is
controlled and no external file or host path is involved.

StarRocks does NOT create tables on write — the connector only issues ``TRUNCATE``
(replace) plus ``INSERT INTO <t> (<cols>) SELECT * FROM FILES(...)`` — so, unlike the
other dests, the targets are the tables the ``world`` model already seeded in each
``starrocks_world_xs_<cloud>`` DB, and the datagen frames are world-shaped
(``caps_world`` -> ``cap_country`` / ``cap_city``).

Those seeded tables use StarRocks' Primary Key model, which decides which mode goes
where:

- ``starrocks_out_append``  : append ``cap_city`` -> ``city``. ``city.id`` is
                              AUTO_INCREMENT and the frame omits it, so each run
                              inserts rows with FRESH keys -> row count GROWS
                              (100 seeded, +3 per run).
- ``starrocks_out_replace`` : replace ``cap_country`` -> ``country``. TRUNCATE +
                              reload -> count STAYS at 3 from the first run on (the
                              239 seeded countries are truncated away).
- ``starrocks_out_none``    : return-None contract (write_out is NOT invoked).

Appending onto ``country`` would NOT grow it: its primary key is ``code``, so re-loading
the same codes upserts in place. Keep append on the AUTO_INCREMENT table.

Schema evolution (``schema_evolution="update"``, which ALTERs the target before the
load) is not exercised here: it is the schema-evolution suites', whose StarRocks lane
creates its own targets rather than widening the seeded world tables.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["caps_input/cap_city"],
)
def starrocks_out_append(city: TableFrameSpec) -> TableFrameSpec:
    # Auto-increment key omitted from the frame -> every re-run adds 3 more rows.
    return city


@subscriber(
    destination=StarRocksDest(tables=["country"], if_table_exists="replace"),
    input_tables=["caps_input/cap_country"],
)
def starrocks_out_replace(country: TableFrameSpec) -> TableFrameSpec:
    # TRUNCATE + reload -> count stays at 3 however often this runs. The world
    # table's surface_area is DECIMAL(10,2) and the frame's a float: a change of
    # type, which strict refuses, so the frame takes the column's type.
    return country.cast({"surface_area": pl.Decimal(10, 2)})


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["caps_input/cap_city"],
)
def starrocks_out_none(city: TableFrameSpec) -> TableFrameSpec:
    # Return-None contract: write_out is NOT invoked (city is left untouched).
    return None
