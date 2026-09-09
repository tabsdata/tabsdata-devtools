#
# Copyright 2026 Tabsdata Inc.
#
"""Expr aggregations — min/max/sum/mean/median/n_unique/count/len."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [3, 1, 2, 4, 4]})
CASE = TFCase(
    inputs={"ag_in": _INPUT},
    checks=[
        Check("ag_min", lambda f, t: t.select(f.col("a").min().alias("r")), unordered_equal),
        Check("ag_max", lambda f, t: t.select(f.col("a").max().alias("r")), unordered_equal),
        Check("ag_sum", lambda f, t: t.select(f.col("a").sum().alias("r")), unordered_equal),
        Check("ag_mean", lambda f, t: t.select(f.col("a").mean().alias("r")), unordered_equal),
        Check("ag_median", lambda f, t: t.select(f.col("a").median().alias("r")), unordered_equal),
        Check("ag_nunique", lambda f, t: t.select(f.col("a").n_unique().alias("r")), unordered_equal),
        Check("ag_count", lambda f, t: t.select(f.col("a").count().alias("r")), unordered_equal),
        Check("ag_len", lambda f, t: t.select(f.col("a").len().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ag_in"])
def ag_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ag_in@NEW"], output_tables=CASE.output_names)
def ag_tfr(
    t: TableFrameSpec,
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
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ag_sub(
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
