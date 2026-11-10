#
# Copyright 2026 Tabsdata Inc.
#
"""Expr arithmetic operators — ``+ - * / // % **`` via col-to-col and col-to-literal."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [6, 7, 8], "b": [2, 3, 4]})
CASE = TFCase(
    inputs={"arith_in": _INPUT},
    checks=[
        Check("ar_add", lambda f, t: t.select((f.col("a") + f.col("b")).alias("r")), unordered_equal),
        Check("ar_sub", lambda f, t: t.select((f.col("a") - f.col("b")).alias("r")), unordered_equal),
        Check("ar_mul", lambda f, t: t.select((f.col("a") * f.col("b")).alias("r")), unordered_equal),
        Check("ar_truediv", lambda f, t: t.select((f.col("a") / f.col("b")).alias("r")), unordered_equal),
        Check("ar_floordiv", lambda f, t: t.select((f.col("a") // f.col("b")).alias("r")), unordered_equal),
        Check("ar_mod", lambda f, t: t.select((f.col("a") % f.col("b")).alias("r")), unordered_equal),
        Check("ar_pow", lambda f, t: t.select((f.col("a") ** 2).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["arith_in"])
def arith_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/arith_in@NEW"], output_tables=CASE.output_names)
def arith_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def arith_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6])
    return TableFrame.empty()
