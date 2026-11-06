#
# Copyright 2026 Tabsdata Inc.
#
"""EXAMPLE · two ``grok`` calls in one transformer — the line AND the file it came from.

Same plain shape as ``gk_ex_cities``, with the two things a real log pipeline usually
needs on top of the basic split:

* a NUMERIC capture (``%{NUMBER}`` cast to ``Float64``) that downstream arithmetic can
  use straight away — here a percentage turned into a share with ``with_columns``;
* a second ``grok`` call on the ``file`` column. ``SrcFileFormat.LOG`` gives every row the
  bare name of the file it was read from (``country_language_20260204T091500_412.csv``),
  and that name carries the batch's identity — so grok it too and the parsed rows arrive
  tagged with which entity and which load produced them.

Both calls sit in ONE transformer body, chained: ``grok`` returns a TableFrame, so the
second call is just a method call on the first one's result.

    csv/country_language_<stamp>.csv       gk_marts/languages
    ABW,Dutch,T,5.3                     -> country_code ABW   entity     country_language
                                           language     Dutch load_day   20260204
                                           is_official  T     load_stamp 091500_412
                                           percentage   5.3   share      0.053

Run it offline (no server, no domain) with::

    python suites/grok/functions/gk_ex_langs.py
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import col, concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

# `country_code,language,is_official,percentage` — `%{NUMBER}` matches an integer or a
# decimal (`5.3`, `76.7`), and the schema below casts it to a real Float64 column.
LANG_LINE = r"^%{WORD:code},%{DATA:language},%{WORD:official},%{NUMBER:pct}$"
LANG_SCHEMA = {
    "code": CD("country_code", td.String),
    "language": CD("language", td.String),
    "official": CD("is_official", td.String),
    "pct": CD("percentage", td.Float64),
}

# The staged file's own name: `<entity>_<YYYYMMDD>T<hhmmss>_<millis>.csv`. `%{DATA}` is
# non-greedy, so `entity` stops at the `_` that precedes the date — which is why
# `country_language` comes back whole instead of being cut at the first underscore.
FILE_NAME = r"^%{DATA:entity}_%{INT:day}T%{DATA:stamp}\.csv$"
FILE_SCHEMA = {
    "entity": CD("entity", td.String),
    "day": CD("load_day", td.Int64),
    "stamp": CD("load_stamp", td.String),
}


# --- ingest: the staged CSV, read as a log (gk_logs) --------------------------
@publisher(
    source=LocalFileSrc(paths=["csv/country_language_2*.csv"], format=SrcFileFormat.LOG),
    output_tables=["lang_lines"],
)
def lang_log_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


# --- parse: two grok calls, then ordinary column work (gk_marts) --------------
@transformer(input_tables=["gk_logs/lang_lines@NEW"], output_tables=["languages"])
def parse_lang_log(log_versions: TableFramesSpec) -> TableFrameSpec:
    log = concat(log_versions or [])
    return (
        # Chained: parse the line, then parse the file name of the row you just parsed.
        log.grok("message", LANG_LINE, LANG_SCHEMA)
        .grok("file", FILE_NAME, FILE_SCHEMA)
        # The header line matched neither the line pattern nor anything typed — drop it.
        .filter(col("country_code").is_not_null())
        # `percentage` is already numeric, so this is plain arithmetic, no cast needed.
        .with_columns((col("percentage") / 100).alias("share"))
        .select("country_code", "language", "is_official", "percentage", "share",
                "entity", "load_day", "load_stamp")
    )


# --- mart: the official languages, most-spoken first --------------------------
@transformer(input_tables=["languages@NEW"], output_tables=["official_languages"])
def mart_official_languages(lang_versions: TableFramesSpec) -> TableFrameSpec:
    lang = concat(lang_versions or [])
    return (
        lang.filter(col("is_official") == "T")
        .select("country_code", "language", "percentage", "load_day")
        .sort("percentage", descending=True)
    )


# --- serve: one parquet file per table (gk_out) -------------------------------
@subscriber(
    destination=LocalFileDest(paths=["languages.parquet"]),
    input_tables=["gk_marts/languages"],
)
def languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["official_languages.parquet"]),
    input_tables=["gk_marts/official_languages"],
)
def official_languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- try it offline -----------------------------------------------------------
SAMPLE_FILE = "country_language_20260101T000000_000.csv"
SAMPLE_LINES = (
    "country_code,language,is_official,percentage",  # the header — the non-matching line
    "ABW,Dutch,T,5.3",
    "ABW,Papiamento,F,76.7",
    "AFG,Balochi,F,0.9",
    "AFG,Dari,T,32.1",
)


def demo() -> dict[str, TableFrame]:
    """Run both transformers over :data:`SAMPLE_LINES`; returns ``{table: frame}``.

    A decorated name is a flow DESCRIPTOR, not a callable — the function itself is on
    ``.func``, which is what a local run (or a unit test) calls."""
    log = TableFrame.from_polars(pl.DataFrame({
        "file": [SAMPLE_FILE] * len(SAMPLE_LINES),
        "message": list(SAMPLE_LINES),
    }))
    languages = parse_lang_log.func(log)
    return {"languages": languages,
            "official_languages": mart_official_languages.func(languages)}


if __name__ == "__main__":
    for name, frame in demo().items():
        print(f"== {name} ==")
        print(frame._to_polars_lf().collect())
