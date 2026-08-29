#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.grok — the core split: one CSV line read as a log becomes typed columns.

The ``city`` entity is the clean case — ``id,name,country_code,district,population``,
no field ever quoted — so a comma-delimited pattern parses every data line, and the
CSV's HEADER line is the only non-match (grok fills its captures with null).

Two calls: the full five-capture split, and a SUBSET split showing you capture only the
fields you want (the ones in between are matched but discarded, un-named).
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.dev import TrashDest
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

try:
    from ._harness import (
        FILE, MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, has_columns, nulls, row,
    )
except ImportError:
    from _harness import (
        FILE, MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, has_columns, nulls, row,
    )

# The header line — the one line no typed pattern can match.
_HEADER = "id,name,country_code,district,population"
_IS_HEADER = pl.col(MESSAGE) == _HEADER
_IS_DATA = pl.col(MESSAGE) != _HEADER

# Anchored end to end so a pattern can only match a WHOLE line: unanchored, `%{INT:id}`
# would happily match the digits inside another field. `%{DATA}` (non-greedy any) is
# what carries a value that may contain spaces or dashes (`Mazar-e-Sharif`,
# `Noord-Holland`); `%{WORD}` would stop at the first one.
_FIELDS = (
    r"^%{INT:id},%{DATA:name},%{WORD:country_code},%{DATA:district},%{INT:population}$"
)

CASE = GrokCase(
    entity="city",
    table="split_lines",
    groks=[
        Grok(
            name="split_fields",
            pattern=_FIELDS,
            # Dict order = output column order. Each ColumnDefinition renames the
            # capture and casts it: every capture arrives as text, the dtype is the
            # cast grok applies on the way out.
            schema={
                "id": CD("city_id", td.Int64),
                "name": CD("city_name", td.String),
                "country_code": CD("country_code", td.String),
                "district": CD("district", td.String),
                "population": CD("population", td.Int64),
            },
            expects=[
                # grok APPENDS columns: the log's own two survive untouched.
                has_columns(FILE, MESSAGE, "city_id", "city_name", "country_code",
                            "district", "population"),
                dtypes(message=pl.String, city_id=pl.Int64, city_name=pl.String,
                       country_code=pl.String, district=pl.String, population=pl.Int64),
                # Known content: the world sample DB's first city.
                row(pl.col("city_id") == 1, city_name="Kabul", country_code="AFG",
                    district="Kabol", population=1780000),
                # Dashes inside two %{DATA} captures, and a 6-digit population.
                row(pl.col("city_id") == 4, city_name="Mazar-e-Sharif",
                    district="Balkh", population=127800),
                row(pl.col("city_id") == 5, city_name="Amsterdam",
                    district="Noord-Holland", population=731200),
                # Every data line parses; the header line parses to nothing.
                filled("city_id", "city_name", "population", where=_IS_DATA),
                nulls(_IS_HEADER, "city_id", "city_name", "country_code", "district",
                      "population"),
            ],
        ),
        Grok(
            name="split_subset",
            # Only the first and last field are named; the three in between are matched
            # by an UN-NAMED %{DATA} each, so they are consumed but not extracted.
            pattern=r"^%{INT:id},%{DATA},%{DATA},%{DATA},%{INT:population}$",
            schema={
                "id": CD("city_id", td.Int64),
                "population": CD("population", td.Int64),
            },
            expects=[
                has_columns(MESSAGE, "city_id", "population"),
                # An un-named capture produces no column.
                dtypes(city_id=pl.Int64, population=pl.Int64),
                row(pl.col("city_id") == 2, population=237500),
                filled("city_id", "population", where=_IS_DATA),
                nulls(_IS_HEADER, "city_id", "population"),
            ],
        ),
    ],
)


@publisher(
    source=LocalFileSrc(paths=CASE.paths, format=SrcFileFormat.LOG),
    output_tables=[CASE.table],
)
def split_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot is a LIST of frames, one per matched
    # file, so union them. The `world` model is reference-only (no modify-data
    # deltas), so today exactly one file matches — concat keeps that an assumption
    # about the data, not about the read.
    return concat(lines)


@transformer(input_tables=[f"{SRC}/{CASE.table}@NEW"], output_tables=CASE.output_names)
def split_tfr(log: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(log)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def split_sub(fields: TableFrameSpec, subset: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([fields, subset])
    return TableFrame.empty()
