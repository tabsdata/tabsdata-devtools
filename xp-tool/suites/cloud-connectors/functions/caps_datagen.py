#
# Copyright 2026 Tabsdata Inc.
#

"""caps_datagen — dev DataGenSrc publishers that feed the per-connector CAPABILITY
suites with controlled, in-process data (no external system).

Two roles:

1. Subscriber INPUT generators (collection ``caps_input`` in the dest capability
   suites — postgres.json, clickhouse.json, ...). They emit tiny, fixed frames so a
   destination's write modes are observable:
   - ``caps_rows``   -> ``cap_rows``   : a small row-set for append/replace/create.
   - ``caps_evo_v1`` -> ``cap_evo_v1`` : NARROW schema (code, name).
   - ``caps_evo_v2`` -> ``cap_evo_v2`` : WIDENED schema (code, name, population) —
     driving schema-evolution when written to the same target as v1.
   - ``caps_world``  -> ``cap_country`` + ``cap_city`` : WORLD-SHAPED frames, for a
     destination that cannot create its target on write (starrocks.json) and so
     writes into the world-model-seeded ``country`` / ``city`` tables.
   Subscribers read these as ``caps_input/<table>``.

2. The dev SOURCE under test (collection ``datagen`` in datagen.json):
   - ``datagen_in``       : base, multi-slot (one frame per Data).
   - ``datagen_in_none``  : return-None contract (nothing published).
   - ``datagen_in_chunk`` : ``Data(df, chunk_size=N)`` — each trigger emits the next
     N rows; re-run to walk the frame (chunked/incremental emission).

DataGenSrc is single-mode: one frame per ``Data`` slot (params are ``TableFrameSpec``,
no ``[0]`` indexing).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc

# --- controlled input frames -------------------------------------------------
# Small so append (grows) vs replace (stays) is obvious by row count.
_ROWS = pl.DataFrame(
    {
        "code": ["USA", "ESP", "JPN"],
        "name": ["United States", "Spain", "Japan"],
        "population": [331002651, 47351567, 125836021],
    }
)
# Schema-evolution pair: v2 adds a `population` column absent from v1.
_EVO_V1 = pl.DataFrame(
    {
        "code": ["USA", "ESP"],
        "name": ["United States", "Spain"],
    }
)
_EVO_V2 = pl.DataFrame(
    {
        "code": ["JPN", "DEU"],
        "name": ["Japan", "Germany"],
        "population": [125836021, 83240525],
    }
)
# 20 rows to walk 5-at-a-time via chunk_size.
_CHUNK = pl.DataFrame(
    {
        "id": list(range(1, 21)),
        "name": [f"row-{i:02d}" for i in range(1, 21)],
    }
)

# World-shaped frames for a destination with NO create-on-write (StarRocks): the
# targets are the tables the `world` model already seeded, so the frames must match
# their DDL. Only the NOT NULL columns are emitted — the connector names the columns
# it loads from the staged parquet, so the nullable ones (indep_year, gnp, ...) are
# simply left NULL. `city.id` is AUTO_INCREMENT and is likewise omitted, so every
# append gets FRESH primary keys (and the row count grows) instead of upserting onto
# the same ones — StarRocks' world tables use the Primary Key model.
_WORLD_COUNTRY = pl.DataFrame(
    {
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
    }
)
_WORLD_CITY = pl.DataFrame(
    {
        "name": ["Washington", "Madrid", "Tokyo"],
        "country_code": ["USA", "ESP", "JPN"],
        "district": ["District of Columbia", "Madrid", "Tokyo-to"],
        "population": [689545, 3223334, 13929286],
    }
)


# --- subscriber INPUT generators (collection `caps_input`) -------------------
@publisher(source=DataGenSrc(data=[Data(_ROWS)]), output_tables=["cap_rows"])
def caps_rows(rows: TableFrameSpec) -> TableFrameSpec:
    # Fixed small row-set; every re-run republishes the same 3 rows.
    return rows


@publisher(source=DataGenSrc(data=[Data(_EVO_V1)]), output_tables=["cap_evo_v1"])
def caps_evo_v1(v1: TableFrameSpec) -> TableFrameSpec:
    # NARROW schema (code, name) -> written first to create the target.
    return v1


@publisher(source=DataGenSrc(data=[Data(_EVO_V2)]), output_tables=["cap_evo_v2"])
def caps_evo_v2(v2: TableFrameSpec) -> TableFrameSpec:
    # WIDENED schema (code, name, population) -> evolves the target created by v1.
    return v2


@publisher(
    source=DataGenSrc(data=[Data(_WORLD_COUNTRY), Data(_WORLD_CITY)]),
    output_tables=["cap_country", "cap_city"],
)
def caps_world(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Multi-slot: one frame per Data. Feeds the StarRocks write modes, whose targets
    # are the seeded `country` / `city` tables (no create-on-write).
    return (country, city)


# --- dev SOURCE under test (collection `datagen`) ----------------------------
@publisher(
    source=DataGenSrc(data=[Data(_ROWS), Data(_EVO_V1)]),
    output_tables=["datagen_rows", "datagen_narrow"],
)
def datagen_in(
    rows: TableFrameSpec,
    narrow: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Multi-slot: one frame per Data.
    return (rows, narrow)


@publisher(source=DataGenSrc(data=[Data(_ROWS)]), output_tables=["datagen_none"])
def datagen_in_none(rows: TableFrameSpec) -> TableFrameSpec:
    # Return-None contract: nothing published this run.
    return None


@publisher(
    source=DataGenSrc(data=[Data(_CHUNK, chunk_size=5)]),
    output_tables=["datagen_chunk"],
)
def datagen_in_chunk(chunk: TableFrameSpec) -> TableFrameSpec:
    # chunk_size=5 -> each trigger emits the next 5 rows; re-run to walk all 20.
    # When exhausted the slot arrives as None -> nothing published.
    return chunk
