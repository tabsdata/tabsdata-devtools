#
# Copyright 2026 Tabsdata Inc.
#

"""showcase · world — the classic `world` sample (countries / cities / languages).

A small end-to-end pipeline in three stages, one collection each:

  world_src  (@publisher)    ingest the three world tables from a Postgres source
  world_marts(@transformer)  enrich / filter into serving views
  world_out  (@subscriber)   write each view out to a local parquet file

Every transform uses the Tabsdata TableFrame API only (join / filter / select /
sort / rename) — no polars. These are ROW-PRESERVING transforms (they carry the
framework's system columns through), which is the shape that sinks reliably. Views
are served one @subscriber per table (a subscriber must return a concrete frame for
every output slot, so single-table sinks stay independent).
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.localfile import LocalFileDest
from tabsdatak.conn.postgres import PostgresSrc
from tabsdatak.conn.snowflake import SnowflakeDest
from tabsdatak.tableframe.functions import col


# --- ingest: Postgres `world` -> world_src -----------------------------------
@publisher(
    source=PostgresSrc(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["country", "city", "country_language"],
)
def pub_world(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    # Pass-through ingest: one query per output table, landed verbatim.
    return (country, city, language)


# --- marts: enrich / filter (world_src -> world_marts) -----------------------
@transformer(
    input_tables=["world_src/city@NEW", "world_src/country@HEAD"],
    output_tables=["cities_enriched"],
)
def tfr_cities_enriched(city: TableFrameSpec, country: TableFrameSpec) -> TableFrameSpec:
    # Attach each city's country name / continent / region (city -> country).
    country_dim = country.select("code", "name", "continent", "region").rename(
        {"name": "country_name"}
    )
    return city.join(
        country_dim, left_on="country_code", right_on="code", how="left"
    ).select("id", "name", "country_code", "country_name", "continent", "region", "population")


@transformer(
    input_tables=["world_src/country_language@NEW", "world_src/country@HEAD"],
    output_tables=["official_languages"],
)
def tfr_official_languages(
    country_language: TableFrameSpec, country: TableFrameSpec
) -> TableFrameSpec:
    # Official languages only, with the country name, most-spoken first.
    country_dim = country.select("code", "name").rename({"name": "country_name"})
    return (
        country_language.filter(col("is_official") == "T")
        .join(country_dim, left_on="country_code", right_on="code", how="left")
        .select("country_code", "country_name", "language", "percentage")
        .sort("percentage", descending=True)
    )


@transformer(input_tables=["world_src/city@NEW"], output_tables=["large_cities"])
def tfr_large_cities(city: TableFrameSpec) -> TableFrameSpec:
    # Cities with more than a million people, largest first.
    return (
        city.filter(col("population") > 1000000)
        .select("id", "name", "country_code", "population")
        .sort("population", descending=True)
    )


# --- serve: one view sink per table (world_marts -> local parquet) -----------
@subscriber(
    destination=LocalFileDest(paths=["cities_enriched.parquet"]),
    input_tables=["world_marts/cities_enriched"],
)
def sink_cities_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["official_languages.parquet"]),
    input_tables=["world_marts/official_languages"],
)
def sink_official_languages(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["large_cities.parquet"]),
    input_tables=["world_marts/large_cities"],
)
def sink_large_cities(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- serve (warehouse): the same marts bulk-loaded into Snowflake ------------
# One mart sink per table (a subscriber must return a concrete frame for every
# output slot). Targets land in the schema of the `snow` domain's connection.
@subscriber(
    destination=SnowflakeDest(tables=["cities_enriched"], if_table_exists="replace"),
    input_tables=["world_marts/cities_enriched"],
)
def snow_cities_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=SnowflakeDest(tables=["official_languages"], if_table_exists="replace"),
    input_tables=["world_marts/official_languages"],
)
def snow_official_languages(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=SnowflakeDest(tables=["large_cities"], if_table_exists="replace"),
    input_tables=["world_marts/large_cities"],
)
def snow_large_cities(t: TableFrameSpec) -> TableFrameSpec:
    return t
