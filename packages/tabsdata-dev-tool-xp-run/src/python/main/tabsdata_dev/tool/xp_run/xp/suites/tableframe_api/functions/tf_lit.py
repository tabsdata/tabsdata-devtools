#
# Copyright 2026 Tabsdata Inc.
#
"""functions.lit — literal scalars with default dtype, explicit dtype, string, and float."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3]})
CASE = TFCase(
    inputs={"lt_in": _INPUT},
    checks=[
        Check("lt_int", lambda f, t: t.with_columns(f.lit(7).alias("c")), unordered_equal),
        Check("lt_dtype", lambda f, t: t.select(f.lit(7, pl.Int16).alias("r")), unordered_equal),
        Check("lt_str", lambda f, t: t.with_columns(f.lit("z").alias("c")), unordered_equal),
        Check("lt_float", lambda f, t: t.select(f.lit(1.5).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["lt_in"])
def lt_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/lt_in@NEW"], output_tables=CASE.output_names)
def lt_tfr(
    t: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def lt_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
