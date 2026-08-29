#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.grok — the dtype half of a ``ColumnDefinition``: every capture is TEXT, and
the definition's dtype is the cast applied on the way out.

Four calls over the same two numeric ``city`` fields (``id``, ``population``), each
asking for different types: signed, unsigned, floating, and the default. The same digits
become Int16/Int32/Int64, UInt16/UInt32, Float32/Float64 or String depending only on the
schema — and a value that does not fit the requested type would fail the cast, so the
types chosen here are ones the ``world`` data always fits (``city.id`` <= 4079, the
largest city population ~10M).
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
    from ._harness import MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, nulls, row
except ImportError:
    from _harness import MESSAGE, OPS, SRC, Grok, GrokCase, dtypes, filled, nulls, row

_HEADER = "id,name,country_code,district,population"
_IS_HEADER = pl.col(MESSAGE) == _HEADER
_IS_DATA = pl.col(MESSAGE) != _HEADER

# One pattern, reused by every call: two named numeric captures with the string fields
# consumed un-named in between. `%{INT}` captures the digits; the dtype does the rest.
_PATTERN = r"^%{INT:id},%{DATA},%{DATA},%{DATA},%{INT:pop}$"

CASE = GrokCase(
    entity="city",
    table="types_lines",
    groks=[
        Grok(
            name="types_signed",
            pattern=_PATTERN,
            schema={"id": CD("id_i16", td.Int16), "pop": CD("pop_i64", td.Int64)},
            expects=[
                dtypes(id_i16=pl.Int16, pop_i64=pl.Int64),
                row(pl.col("id_i16") == 1, pop_i64=1780000),
                filled("id_i16", "pop_i64", where=_IS_DATA),
                nulls(_IS_HEADER, "id_i16", "pop_i64"),
            ],
        ),
        Grok(
            name="types_unsigned",
            pattern=_PATTERN,
            schema={"id": CD("id_u16", td.UInt16), "pop": CD("pop_u32", td.UInt32)},
            expects=[
                dtypes(id_u16=pl.UInt16, pop_u32=pl.UInt32),
                row(pl.col("id_u16") == 6, pop_u32=593321),
                filled("id_u16", "pop_u32", where=_IS_DATA),
            ],
        ),
        Grok(
            name="types_float",
            pattern=_PATTERN,
            # The same digit strings, cast to floating point: an integer capture is not
            # tied to an integer column.
            schema={"id": CD("id_f32", td.Float32), "pop": CD("pop_f64", td.Float64)},
            expects=[
                dtypes(id_f32=pl.Float32, pop_f64=pl.Float64),
                row(pl.col("id_f32") == 2.0, pop_f64=237500.0),
                filled("id_f32", "pop_f64", where=_IS_DATA),
            ],
        ),
        Grok(
            name="types_default",
            # No dtype at all: `ColumnDefinition` defaults to String, so the captures
            # arrive as the text the pattern matched.
            pattern=_PATTERN,
            schema={"id": CD("id_str"), "pop": CD("pop_str")},
            expects=[
                dtypes(id_str=pl.String, pop_str=pl.String),
                row(pl.col("id_str") == "3", pop_str="186800"),
                filled("id_str", "pop_str", where=_IS_DATA),
                nulls(_IS_HEADER, "id_str", "pop_str"),
            ],
        ),
    ],
)


@publisher(
    source=LocalFileSrc(paths=CASE.paths, format=SrcFileFormat.LOG),
    output_tables=[CASE.table],
)
def types_pub(lines: TableFramesSpec) -> TableFrameSpec:
    # A globbed path is ARRAY mode: the slot is a LIST of frames, one per matched
    # file, so union them. The `world` model is reference-only (no modify-data
    # deltas), so today exactly one file matches — concat keeps that an assumption
    # about the data, not about the read.
    return concat(lines)


@transformer(input_tables=[f"{SRC}/{CASE.table}@NEW"], output_tables=CASE.output_names)
def types_tfr(log: TableFrameSpec) -> tuple[
    TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec
]:
    return CASE.transform(log)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def types_sub(signed: TableFrameSpec, unsigned: TableFrameSpec, floating: TableFrameSpec,
              default: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([signed, unsigned, floating, default])
    return TableFrame.empty()
