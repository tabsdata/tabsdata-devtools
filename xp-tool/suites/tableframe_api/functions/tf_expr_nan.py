#
# Copyright 2026 Tabsdata Inc.
#
"""Expr NaN / infinity handling — ``is_nan is_not_nan is_finite is_infinite fill_nan``."""
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

_INPUT = pl.DataFrame({"a": [1.0, float("nan"), float("inf"), float("-inf")]})
CASE = TFCase(
    inputs={"nan_in": _INPUT},
    checks=[
        Check("nan_is_nan", lambda f, t: t.select(f.col("a").is_nan().alias("r")), unordered_equal),
        Check("nan_is_not_nan", lambda f, t: t.select(f.col("a").is_not_nan().alias("r")), unordered_equal),
        Check("nan_is_finite", lambda f, t: t.select(f.col("a").is_finite().alias("r")), unordered_equal),
        Check("nan_is_infinite", lambda f, t: t.select(f.col("a").is_infinite().alias("r")), unordered_equal),
        Check("nan_fill", lambda f, t: t.select(f.col("a").fill_nan(0.0).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["nan_in"])
def nan_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/nan_in@NEW"], output_tables=CASE.output_names)
def nan_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def nan_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
