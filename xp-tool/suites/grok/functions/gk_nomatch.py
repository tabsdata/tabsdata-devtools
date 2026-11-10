#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.grok — the null contract: a line the pattern does not match keeps its row
and gets NULL captures. grok never drops a row and never raises on a bad line, which is
what makes it usable on real log input where some lines are headers, banners or junk.

Three calls over ``city``:
  * a pattern with a LITERAL in it, matching only the Dutch cities — every other line
    comes back null, so one pass partitions the file;
  * an OPTIONAL capture (raw regex ``(?:...)?`` around a grok pattern) that nothing in
    the file satisfies — matched lines parse, the optional column stays null;
  * the same split followed by a row-preserving ``filter`` that DROPS the non-matching
    rows — the idiomatic way to keep only parsed lines.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.dev import TrashDest
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe import TableFrame, datatypes as td
from tabsdatak.tableframe.functions import col, concat
from tabsdatak.tableframe.grok import ColumnDefinition as CD

try:
    from ._harness import (
        MESSAGE, OPS, SRC, Grok, GrokCase, count, dtypes, filled, has_columns, nulls, row,
    )
except ImportError:
    from _harness import (
        MESSAGE, OPS, SRC, Grok, GrokCase, count, dtypes, filled, has_columns, nulls, row,
    )

_HEADER = "id,name,country_code,district,population"
_IS_HEADER = pl.col(MESSAGE) == _HEADER
_IS_DATA = pl.col(MESSAGE) != _HEADER
# Predicates over the RAW LINE, so they are independent of what grok extracted — and
# hold at any data size (the file always has AFG and NLD cities among the first rows).
_IS_NLD = pl.col(MESSAGE).str.contains(",NLD,")
_IS_AFG = pl.col(MESSAGE).str.contains(",AFG,")

_FIELDS = (
    r"^%{INT:id},%{DATA:name},%{WORD:country_code},%{DATA:district},%{INT:population}$"
)

CASE = GrokCase(
    entity="city",
    table="nomatch_lines",
    groks=[
        Grok(
            name="nomatch_literal",
            # `NLD` is a literal, not a capture: the pattern can only match a Dutch city.
            pattern=r"^%{INT:id},%{DATA:name},NLD,%{DATA:district},%{INT:population}$",
            schema={
                "id": CD("nld_id", td.Int64),
                "name": CD("nld_name", td.String),
                "district": CD("nld_district", td.String),
                "population": CD("nld_population", td.Int64),
            },
            expects=[
                # Matching lines parse in full...
                filled("nld_id", "nld_name", "nld_district", "nld_population",
                       where=_IS_NLD),
                row(pl.col("nld_name") == "Amsterdam", nld_id=5,
                    nld_district="Noord-Holland", nld_population=731200),
                # ...and every other line keeps its row with null captures.
                nulls(_IS_AFG, "nld_id", "nld_name", "nld_district", "nld_population"),
                nulls(_IS_HEADER, "nld_id", "nld_name"),
            ],
        ),
        Grok(
            name="nomatch_optional",
            # A grok pattern inside an optional raw-regex group. `city` has exactly five
            # fields, so the sixth never appears and `extra` is null on every line —
            # while the five real captures still parse.
            pattern=(r"^%{INT:id},%{DATA:name},%{WORD:country_code},%{DATA:district},"
                     r"%{INT:population}(?:,%{WORD:extra})?$"),
            schema={
                "id": CD("city_id", td.Int64),
                "name": CD("city_name", td.String),
                "country_code": CD("country_code", td.String),
                "district": CD("district", td.String),
                "population": CD("population", td.Int64),
                "extra": CD("extra", td.String),
            },
            expects=[
                has_columns("city_id", "extra"),
                dtypes(city_id=pl.Int64, extra=pl.String),
                filled("city_id", "city_name", "population", where=_IS_DATA),
                # The optional capture never participates: null even where the line
                # matched. (An unmatched optional group yields null, not an empty string.)
                nulls(_IS_DATA, "extra"),
            ],
        ),
        Grok(
            name="nomatch_filtered",
            pattern=_FIELDS,
            schema={
                "id": CD("city_id", td.Int64),
                "name": CD("city_name", td.String),
                "population": CD("population", td.Int64),
            },
            # Drop what did not parse. `filter` is row-preserving in the sense the sink
            # requires (it carries the system columns through), so the filtered frame is
            # a valid transformer output — unlike a grouped one.
            then=lambda t: t.filter(col("city_id").is_not_null()),
            expects=[
                # The header line is gone entirely, not merely null.
                count(_IS_HEADER, 0),
                filled("city_id", "city_name", "population"),
                row(pl.col("city_id") == 1, city_name="Kabul", population=1780000),
            ],
        ),
    ],
)


@publisher(
    source=LocalFileSrc(paths=CASE.paths, format=SrcFileFormat.LOG),
    output_tables=[CASE.table],
)
def nomatch_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot is a LIST of frames, one per matched
    # file, so union them. The `world` model is reference-only (no modify-data
    # deltas), so today exactly one file matches — concat keeps that an assumption
    # about the data, not about the read.
    return concat(lines)


@transformer(input_tables=[f"{SRC}/{CASE.table}@NEW"], output_tables=CASE.output_names)
def nomatch_tfr(log_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    log = concat(log_versions or [])
    return CASE.transform(log)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def nomatch_sub(literal: TableFrameSpec, optional: TableFrameSpec,
                filtered: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([literal, optional, filtered])
    return TableFrame.empty()
