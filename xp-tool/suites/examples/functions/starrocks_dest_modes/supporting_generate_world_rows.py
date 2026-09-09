#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example, but the reason this suite looks different.

StarRocks does NOT create tables on write: the connector only issues `TRUNCATE`
(for replace) plus `INSERT INTO <t> (<cols>) SELECT * FROM FILES(...)`. So the
targets must ALREADY EXIST, and the frames must match their DDL.

This suite therefore writes into the tables the `world` model already seeded in
the backing domain, and the frames below are world-shaped. Only the NOT NULL
columns are emitted — the connector names the columns it loads from the staged
parquet, so the nullable ones are simply left NULL.

`city.id` is AUTO_INCREMENT and is deliberately omitted, so every append gets
FRESH keys and the row count GROWS. `country`'s primary key is `code`, so
appending the same codes would upsert in place instead — which is why the append
example targets `city` and the replace example targets `country`.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "code": ["USA", "ESP", "JPN"],
                "name": ["United States", "Spain", "Japan"],
                "continent": ["North America", "Europe", "Asia"],
                "region": ["North America", "Southern Europe", "Eastern Asia"],
                "surface_area": [9363520.0, 505992.0, 377829.0],
                "population": [331002651, 47351567, 125836021],
                "local_name": ["United States", "Espana", "Nippon"],
                "government_form": [
                    "Federal Republic",
                    "Constitutional Monarchy",
                    "Constitutional Monarchy",
                ],
                "code2": ["US", "ES", "JP"],
            })),
            Data(pl.DataFrame({
                "name": ["Washington", "Madrid", "Tokyo"],
                "country_code": ["USA", "ESP", "JPN"],
                "district": ["District of Columbia", "Madrid", "Tokyo-to"],
                "population": [689545, 3223334, 13929286],
            })),
        ]
    ),
    output_tables=["world_country", "world_city"],
)
def generate_world_rows(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)
