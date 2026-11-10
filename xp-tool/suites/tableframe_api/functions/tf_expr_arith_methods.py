#
# Copyright 2026 Tabsdata Inc.
#
"""Expr arithmetic methods — add/sub/mul/truediv/floordiv/mod/pow/neg."""
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
    inputs={"arm_in": _INPUT},
    checks=[
        Check("arm_add", lambda f, t: t.select(f.col("a").add(f.col("b")).alias("r")), unordered_equal),
        Check("arm_sub", lambda f, t: t.select(f.col("a").sub(f.col("b")).alias("r")), unordered_equal),
        Check("arm_mul", lambda f, t: t.select(f.col("a").mul(f.col("b")).alias("r")), unordered_equal),
        Check("arm_truediv", lambda f, t: t.select(f.col("a").truediv(f.col("b")).alias("r")), unordered_equal),
        Check("arm_floordiv", lambda f, t: t.select(f.col("a").floordiv(f.col("b")).alias("r")), unordered_equal),
        Check("arm_mod", lambda f, t: t.select(f.col("a").mod(f.col("b")).alias("r")), unordered_equal),
        Check("arm_pow", lambda f, t: t.select(f.col("a").pow(2).alias("r")), unordered_equal),
        Check("arm_neg", lambda f, t: t.select(f.col("a").neg().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["arm_in"])
def arm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/arm_in@NEW"], output_tables=CASE.output_names)
def arm_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
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
def arm_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7])
    return TableFrame.empty()
