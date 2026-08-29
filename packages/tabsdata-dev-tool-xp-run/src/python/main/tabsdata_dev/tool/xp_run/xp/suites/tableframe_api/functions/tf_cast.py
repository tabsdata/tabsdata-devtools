#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.cast — int->float, float->int (truncating), and numeric->string,
each via a {column: dtype} mapping."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3], "b": [4.5, 5.5, 6.5]})
CASE = TFCase(
    inputs={"ct_in": _INPUT},
    checks=[
        Check("ct_int_to_float", lambda f, t: t.cast({"a": pl.Float64}), unordered_equal),
        Check("ct_float_to_int", lambda f, t: t.cast({"b": pl.Int64}), unordered_equal),
        Check("ct_to_str", lambda f, t: t.cast({"a": pl.String}), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ct_in"])
def ct_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ct_in@NEW"], output_tables=CASE.output_names)
def ct_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ct_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
