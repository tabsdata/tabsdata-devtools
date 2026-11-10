#
# Copyright 2026 Tabsdata Inc.
#
"""EXAMPLE · ``grok`` inside an ordinary transformer — city log lines to a typed table.

This is the plain shape you would write in your own project: no harness, no expectation
objects, no ``CASE`` — a publisher, transformers whose bodies call ``TableFrame.grok``
inline, and subscribers that write the result out as parquet::

    csv/city_<stamp>.csv          gk_logs/city_lines            gk_marts/cities
    1,Kabul,AFG,Kabol,1780000  -> message "1,Kabul,AFG,…"    -> city_id      1
                                  file    "city_2026….csv"      city_name    Kabul
                                                                country_code AFG
                                                                district     Kabol
                                                                population   1780000

The input is the ``world`` model's own ``city`` CSV read with ``SrcFileFormat.LOG``,
which delivers ONE ROW PER LINE with two columns — ``file`` (the file's bare name) and
``message`` (the whole line, commas and all). The publisher lands those lines untouched;
the parsing happens in the transformer, which is the point of the example.

Two things worth copying from ``parse_city_log`` below:

* ``grok`` APPENDS one column per named capture and keeps the column it parsed, so what
  follows the call is just ordinary TableFrame work — ``filter`` / ``select`` / ``sort``,
  exactly as on any other table.
* a line the pattern does not match comes back with NULL captures rather than failing the
  run (here the CSV's header line), so a real pipeline filters those rows out — or routes
  them somewhere — right after the parse.

Run it offline (no server, no domain) with::

    python suites/grok/functions/gk_ex_cities.py
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import col, concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

# One capture per CSV field. `%{DATA}` is the non-greedy "anything up to the next
# delimiter" pattern — it is what carries a value containing spaces or dashes
# (`Mazar-e-Sharif`, `Noord-Holland`); `%{WORD}` would stop at the first one. The `^`/`$`
# anchors keep a pattern from matching some substring in the middle of a line.
CITY_LINE = (
    r"^%{INT:id},%{DATA:name},%{WORD:country_code},%{DATA:district},%{INT:population}$"
)

# capture name -> output column. The ColumnDefinition renames the capture and casts it:
# every capture arrives as text, the dtype is the cast grok applies on the way out. The
# dict order is the order the new columns are appended in.
CITY_SCHEMA = {
    "id": CD("city_id", td.Int64),
    "name": CD("city_name", td.String),
    "country_code": CD("country_code", td.String),
    "district": CD("district", td.String),
    "population": CD("population", td.Int64),
}


# --- ingest: the staged CSV, read as a log (gk_logs) --------------------------
@publisher(
    # The stamp in `city_<YYYYMMDD>T<hhmmss_mmm>.csv` is globbed away from its leading `2`
    # (the year) — `city_*` would be fine here, but `country_*` would also match
    # `country_language_*`, so the suite writes every glob this way.
    source=LocalFileSrc(paths=["csv/city_2*.csv"], format=SrcFileFormat.LOG),
    output_tables=["city_lines"],
)
def city_log_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot holds one frame per matched file, so union
    # them. No parsing here — the raw lines are landed as they came off disk.
    return concat(lines)


# --- parse: grok in a regular transformer (gk_marts) --------------------------
@transformer(input_tables=["gk_logs/city_lines@NEW"], output_tables=["cities"])
def parse_city_log(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    parsed = log.grok("message", CITY_LINE, CITY_SCHEMA)
    return (
        # The CSV header line matches no typed pattern, so its captures are null — drop
        # it (and any other unparsed line) by testing a column the pattern must fill.
        parsed.filter(col("city_id").is_not_null())
        # `file` and `message` survived the grok call; keep only the parsed columns.
        .select("city_id", "city_name", "country_code", "district", "population")
    )


# --- mart: an ordinary transform over the parsed table ------------------------
# A table produced in the same collection is referenced by its BARE name (a
# `collection/table` reference is for crossing collections).
@transformer(input_tables=["cities@NEW"], output_tables=["big_cities"])
def mart_big_cities(city_versions: TableFramesSpec) -> TableFrameSpec:
    # Nothing here knows the table came from a log: past the grok call it is a table.
    city = concat(city_versions or [])
    return (
        city.filter(col("population") > 1000000)
        .select("city_id", "city_name", "country_code", "population")
        .sort("population", descending=True)
    )


# --- serve: one parquet file per table (gk_out) -------------------------------
@subscriber(
    destination=LocalFileDest(paths=["cities.parquet"]),
    input_tables=["gk_marts/cities"],
)
def cities_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["big_cities.parquet"]),
    input_tables=["gk_marts/big_cities"],
)
def big_cities_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- try it offline -----------------------------------------------------------
# The same transformer bodies over a handful of sample lines, shaped exactly as
# SrcFileFormat.LOG delivers them. A decorated name is a flow DESCRIPTOR, not a callable:
# the function itself is on `.func`, which is what a local run (or a unit test) calls.
SAMPLE_LINES = (
    "id,name,country_code,district,population",  # the header — the non-matching line
    "1,Kabul,AFG,Kabol,1780000",
    "2,Qandahar,AFG,Qandahar,237500",
    "4,Mazar-e-Sharif,AFG,Balkh,127800",
    "5,Amsterdam,NLD,Noord-Holland,731200",
)


def demo() -> dict[str, TableFrame]:
    """Run the parse and the mart over :data:`SAMPLE_LINES`; returns ``{table: frame}``."""
    log = TableFrame.from_polars(pl.DataFrame({
        "file": ["city_20260101T000000_000.csv"] * len(SAMPLE_LINES),
        "message": list(SAMPLE_LINES),
    }))
    cities = parse_city_log.func([log])
    return {"cities": cities, "big_cities": mart_big_cities.func([cities])}


if __name__ == "__main__":
    for name, frame in demo().items():
        print(f"== {name} ==")
        print(frame._to_polars_lf().collect())
