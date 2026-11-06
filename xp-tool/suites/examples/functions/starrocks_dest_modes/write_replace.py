#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — StarRocks destination: `if_table_exists="replace"`.

TRUNCATE + reload, so the count STAYS at three from the first run on — the 239
seeded countries are truncated away, which is worth knowing before pointing this
at anything you care about.

WHY THIS TARGET AND NOT `city`: `country`'s primary key is `code`, so an APPEND
of the same three codes would upsert in place and the count would never move —
a confusing demonstration. Append belongs on the AUTO_INCREMENT table, replace on
the keyed one. StarRocks' Primary Key model is what makes the choice matter.

THE CAST: a StarRocks replace keeps the seeded table, so the frame meets the
table's own types, and `surface_area` is a DECIMAL(10,2) there but a float in the
frame. That is a change of type, which the default `schema_evolution="strict"`
refuses (SQL_COMMON_10), so the frame takes the column's type first.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["country"], if_table_exists="replace"),
    input_tables=["gen/world_country"],
)
def write_replace(country: TableFrameSpec) -> TableFrameSpec:
    return country.cast({"surface_area": pl.Decimal(10, 2)})
