#
# Copyright 2026 Tabsdata Inc.
#
"""Expr power/exponential/logarithm methods — sqrt/cbrt/exp and log/log(base)/log10/log1p."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"x": [1.0, 2.0, 4.0]})
CASE = TFCase(
    inputs={"el_in": _INPUT},
    checks=[
        Check("el_sqrt", lambda f, t: t.select(f.col("x").sqrt().alias("r")), unordered_equal),
        Check("el_cbrt", lambda f, t: t.select(f.col("x").cbrt().alias("r")), unordered_equal),
        Check("el_exp", lambda f, t: t.select(f.col("x").exp().alias("r")), unordered_equal),
        Check("el_log", lambda f, t: t.select(f.col("x").log().alias("r")), unordered_equal),
        Check("el_log_base", lambda f, t: t.select(f.col("x").log(10).alias("r")), unordered_equal),
        Check("el_log10", lambda f, t: t.select(f.col("x").log10().alias("r")), unordered_equal),
        Check("el_log1p", lambda f, t: t.select(f.col("x").log1p().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["el_in"])
def el_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/el_in@NEW"], output_tables=CASE.output_names)
def el_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def el_sub(
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
