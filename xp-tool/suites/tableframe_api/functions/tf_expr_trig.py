#
# Copyright 2026 Tabsdata Inc.
#
"""Expr trigonometric methods — sin/cos/tan/cot and their inverses arcsin/arccos/arctan."""
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

_INPUT = pl.DataFrame({"x": [0.2, 0.5, 0.8]})
CASE = TFCase(
    inputs={"tg_in": _INPUT},
    checks=[
        Check("tg_sin", lambda f, t: t.select(f.col("x").sin().alias("r")), unordered_equal),
        Check("tg_cos", lambda f, t: t.select(f.col("x").cos().alias("r")), unordered_equal),
        Check("tg_tan", lambda f, t: t.select(f.col("x").tan().alias("r")), unordered_equal),
        Check("tg_cot", lambda f, t: t.select(f.col("x").cot().alias("r")), unordered_equal),
        Check("tg_arcsin", lambda f, t: t.select(f.col("x").arcsin().alias("r")), unordered_equal),
        Check("tg_arccos", lambda f, t: t.select(f.col("x").arccos().alias("r")), unordered_equal),
        Check("tg_arctan", lambda f, t: t.select(f.col("x").arctan().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["tg_in"])
def tg_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/tg_in@NEW"], output_tables=CASE.output_names)
def tg_tfr(
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
def tg_sub(
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
