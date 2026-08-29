#
# Copyright 2026 Tabsdata Inc.
#
"""Expr comparison operators — ``== != < <= > >=`` producing boolean columns."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3], "b": [2, 2, 2]})
CASE = TFCase(
    inputs={"cmp_in": _INPUT},
    checks=[
        Check("cmp_eq", lambda f, t: t.select((f.col("a") == f.col("b")).alias("r")), unordered_equal),
        Check("cmp_ne", lambda f, t: t.select((f.col("a") != f.col("b")).alias("r")), unordered_equal),
        Check("cmp_lt", lambda f, t: t.select((f.col("a") < f.col("b")).alias("r")), unordered_equal),
        Check("cmp_le", lambda f, t: t.select((f.col("a") <= f.col("b")).alias("r")), unordered_equal),
        Check("cmp_gt", lambda f, t: t.select((f.col("a") > f.col("b")).alias("r")), unordered_equal),
        Check("cmp_ge", lambda f, t: t.select((f.col("a") >= f.col("b")).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["cmp_in"])
def cmp_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/cmp_in@NEW"], output_tables=CASE.output_names)
def cmp_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def cmp_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
