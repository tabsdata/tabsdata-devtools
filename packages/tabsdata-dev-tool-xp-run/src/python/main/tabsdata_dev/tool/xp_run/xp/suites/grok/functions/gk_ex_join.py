#
# Copyright 2026 Tabsdata Inc.
#
"""EXAMPLE · joining two groked logs — parsed lines are just tables.

Two different files are read as logs and parsed with their own pattern, then JOINED. The
point of the example is what happens after the ``grok`` calls: nothing about the result
remembers it came from a log, so the join, the rename and the sort are the ordinary
TableFrame code you would write over any two tables.

    csv/city_<stamp>.csv             -> jn_cities  (city_id, city_name, country_code, …)
                                                        \\  join on country_code
    csv/country_language_<stamp>.csv -> jn_languages (country_code, language, …)
                                                        /
                                        gk_marts/city_languages

The join is a LEFT join against the official-languages side, so a city whose country has
no official language row keeps its row with nulls — the same choice you would make for
any dimension lookup. A country with two official languages contributes two rows for each
of its cities; that is the join talking, not grok.

Each example file stands on its own, so this one publishes its own ``jn_``-prefixed lines
tables (one publisher, one output table per source path) rather than borrowing the ones
``gk_ex_cities`` / ``gk_ex_langs`` publish.

Run it offline (no server, no domain) with::

    python suites/grok/functions/gk_ex_join.py
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import col, concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

CITY_LINE = (
    r"^%{INT:id},%{DATA:name},%{WORD:country_code},%{DATA:district},%{INT:population}$"
)
CITY_SCHEMA = {
    "id": CD("city_id", td.Int64),
    "name": CD("city_name", td.String),
    "country_code": CD("country_code", td.String),
    "district": CD("district", td.String),
    "population": CD("population", td.Int64),
}

LANG_LINE = r"^%{WORD:code},%{DATA:language},%{WORD:official},%{NUMBER:pct}$"
LANG_SCHEMA = {
    "code": CD("country_code", td.String),
    "language": CD("language", td.String),
    "official": CD("is_official", td.String),
    "pct": CD("percentage", td.Float64),
}


# --- ingest: two staged CSVs, both read as logs (gk_logs) ---------------------
# ONE publisher, two paths: a file source gives one output slot PER PATH, so the two
# files land as two tables from a single function — which also keeps both sides of the
# join in the same plan, so the join runs once, after both parses.
@publisher(
    source=LocalFileSrc(
        paths=["csv/city_2*.csv", "csv/country_language_2*.csv"],
        format=SrcFileFormat.LOG,
    ),
    output_tables=["jn_city_lines", "jn_lang_lines"],
)
def jn_log_pub(
    cities: TableFramesSpec, languages: TableFramesSpec
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Each slot is a LIST (its path is a glob), so union each one into its table.
    return concat(cities), concat(languages)


# --- parse: one transformer per log (gk_marts) --------------------------------
@transformer(input_tables=["gk_logs/jn_city_lines@NEW"], output_tables=["jn_cities"])
def jn_parse_cities(log: TableFrameSpec) -> TableFrameSpec:
    return (
        log.grok("message", CITY_LINE, CITY_SCHEMA)
        .filter(col("city_id").is_not_null())
        .select("city_id", "city_name", "country_code", "population")
    )


@transformer(input_tables=["gk_logs/jn_lang_lines@NEW"], output_tables=["jn_languages"])
def jn_parse_languages(log: TableFrameSpec) -> TableFrameSpec:
    return (
        log.grok("message", LANG_LINE, LANG_SCHEMA)
        .filter(col("country_code").is_not_null())
        .select("country_code", "language", "is_official", "percentage")
    )


# --- mart: join the two parsed tables -----------------------------------------
# Both inputs live in this collection, so both are referenced by their bare name (a
# `collection/table` reference is for crossing collections). Both are @NEW: this function
# runs when a new version of either parsed table lands — which, since one publisher feeds
# both, means once, after the two parses of the same run.
@transformer(
    input_tables=["jn_cities@NEW", "jn_languages@NEW"],
    output_tables=["city_languages"],
)
def mart_city_languages(city: TableFrameSpec, lang: TableFrameSpec) -> TableFrameSpec:
    official = (
        lang.filter(col("is_official") == "T")
        .select("country_code", "language", "percentage")
        # Rename before the join so the mart says what the columns mean — and so nothing
        # collides with a column on the city side.
        .rename({"language": "official_language", "percentage": "speakers_pct"})
    )
    return (
        city.join(official, left_on="country_code", right_on="country_code", how="left")
        .select("city_id", "city_name", "country_code", "population",
                "official_language", "speakers_pct")
        .sort("population", descending=True)
    )


# --- serve: the mart as parquet (gk_out) --------------------------------------
@subscriber(
    destination=LocalFileDest(paths=["city_languages.parquet"]),
    input_tables=["gk_marts/city_languages"],
)
def city_languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- try it offline -----------------------------------------------------------
CITY_LINES = (
    "id,name,country_code,district,population",
    "1,Kabul,AFG,Kabol,1780000",
    "2,Qandahar,AFG,Qandahar,237500",
    "5,Amsterdam,NLD,Noord-Holland,731200",
)
LANG_LINES = (
    "country_code,language,is_official,percentage",
    "AFG,Balochi,F,0.9",
    "AFG,Dari,T,32.1",
    "AFG,Pashto,T,52.4",
    "NLD,Dutch,T,95.6",
)


def _log(entity: str, lines: tuple[str, ...]) -> TableFrame:
    # What SrcFileFormat.LOG delivers: the file's bare name, and one row per line.
    return TableFrame.from_polars(pl.DataFrame({
        "file": [f"{entity}_20260101T000000_000.csv"] * len(lines),
        "message": list(lines),
    }))


def demo() -> dict[str, TableFrame]:
    """Run the two parses and the join over the sample lines; ``{table: frame}``.

    A decorated name is a flow DESCRIPTOR, not a callable — the function itself is on
    ``.func``, which is what a local run (or a unit test) calls."""
    cities = jn_parse_cities.func(_log("city", CITY_LINES))
    languages = jn_parse_languages.func(_log("country_language", LANG_LINES))
    return {
        "jn_cities": cities,
        "jn_languages": languages,
        "city_languages": mart_city_languages.func(cities, languages),
    }


if __name__ == "__main__":
    for name, frame in demo().items():
        print(f"== {name} ==")
        print(frame._to_polars_lf().collect())
