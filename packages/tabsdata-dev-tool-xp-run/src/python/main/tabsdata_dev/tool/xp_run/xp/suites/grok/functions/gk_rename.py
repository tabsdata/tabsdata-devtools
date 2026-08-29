#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.grok — what the ``ColumnDefinition`` schema controls: the output column's
NAME, and the output column ORDER.

Three calls over ``country_language`` (``country_code,language,is_official,percentage``):
the same four captures, renamed / not renamed / reordered. The capture name lives only
in the pattern; the schema decides what the column is called, and the schema DICT ORDER
— not the order the captures appear in the pattern — decides the column order.
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
        MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, has_columns, no_columns, nulls, order, row,
    )
except ImportError:
    from _harness import (
        MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, has_columns, no_columns, nulls, order, row,
    )

_HEADER = "country_code,language,is_official,percentage"
_IS_HEADER = pl.col(MESSAGE) == _HEADER

# Short capture names on purpose, so a renamed column cannot be confused with its
# capture. `%{DATA:lang}` because a language may contain spaces (`Crioulo Portugues`).
_PATTERN = r"^%{WORD:cc},%{DATA:lang},%{WORD:official},%{NUMBER:pct}$"

CASE = GrokCase(
    entity="country_language",
    table="rename_lines",
    groks=[
        Grok(
            name="rename_renamed",
            pattern=_PATTERN,
            schema={
                "cc": CD("country_code", td.String),
                "lang": CD("language", td.String),
                "official": CD("is_official", td.String),
                "pct": CD("percentage", td.Float64),
            },
            expects=[
                has_columns("country_code", "language", "is_official", "percentage"),
                # The capture names must not leak into the output.
                no_columns("cc", "lang", "official", "pct"),
                order("country_code", "language", "is_official", "percentage"),
                dtypes(country_code=pl.String, language=pl.String, is_official=pl.String,
                       percentage=pl.Float64),
                row((pl.col("country_code") == "ABW") & (pl.col("language") == "Papiamento"),
                    is_official="F", percentage=76.7),
                row((pl.col("country_code") == "AFG") & (pl.col("language") == "Dari"),
                    is_official="T", percentage=32.1),
                nulls(_IS_HEADER, "country_code", "language", "is_official", "percentage"),
            ],
        ),
        Grok(
            name="rename_capture_names",
            pattern=_PATTERN,
            # No name in the definition -> the column keeps the CAPTURE name, and only
            # the dtype is applied. `CD()` alone would give a String column.
            schema={
                "cc": CD(dtype=td.String),
                "lang": CD(dtype=td.String),
                "official": CD(dtype=td.String),
                "pct": CD(dtype=td.Float64),
            },
            expects=[
                has_columns("cc", "lang", "official", "pct"),
                no_columns("country_code", "language", "is_official", "percentage"),
                dtypes(cc=pl.String, lang=pl.String, official=pl.String, pct=pl.Float64),
                row((pl.col("cc") == "ABW") & (pl.col("lang") == "Dutch"),
                    official="T", pct=5.3),
            ],
        ),
        Grok(
            name="rename_schema_order",
            pattern=_PATTERN,
            # The very same pattern, whose captures occur in line order (cc, lang,
            # official, pct), with the schema listing them REVERSED. The output follows
            # the schema — and each value still lands in its own capture's column, so
            # the two orders are genuinely independent.
            schema={
                "pct": CD("percentage", td.Float64),
                "official": CD("is_official", td.String),
                "lang": CD("language", td.String),
                "cc": CD("country_code", td.String),
            },
            expects=[
                order("percentage", "is_official", "language", "country_code"),
                row((pl.col("country_code") == "ABW") & (pl.col("language") == "English"),
                    is_official="F", percentage=9.5),
            ],
        ),
    ],
)


@publisher(
    source=LocalFileSrc(paths=CASE.paths, format=SrcFileFormat.LOG),
    output_tables=[CASE.table],
)
def rename_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot is a LIST of frames, one per matched
    # file, so union them. The `world` model is reference-only (no modify-data
    # deltas), so today exactly one file matches — concat keeps that an assumption
    # about the data, not about the read.
    return concat(lines)


@transformer(input_tables=[f"{SRC}/{CASE.table}@NEW"], output_tables=CASE.output_names)
def rename_tfr(log: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(log)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def rename_sub(renamed: TableFrameSpec, captures: TableFrameSpec,
               ordered: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([renamed, captures, ordered])
    return TableFrame.empty()
