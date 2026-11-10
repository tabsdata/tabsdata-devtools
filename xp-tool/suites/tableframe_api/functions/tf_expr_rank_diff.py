#
# Copyright 2026 Tabsdata Inc.
#
"""Expr rank/diff — rank methods (average/min/max/dense/ordinal) and diff n.

Order-sensitive: every check sorts on a unique id first, then verifies with
ordered_equal."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal

_INPUT = pl.DataFrame({"id": [1, 2, 3, 4, 5], "v": [10, 10, 30, 20, 20]})
CASE = TFCase(
    inputs={"rk_in": _INPUT},
    checks=[
        Check("rk_average", lambda f, t: t.sort("id").select(f.col("v").rank().alias("r")), ordered_equal),
        Check("rk_min", lambda f, t: t.sort("id").select(f.col("v").rank("min").alias("r")), ordered_equal),
        Check("rk_max", lambda f, t: t.sort("id").select(f.col("v").rank("max").alias("r")), ordered_equal),
        Check("rk_dense", lambda f, t: t.sort("id").select(f.col("v").rank("dense").alias("r")), ordered_equal),
        Check("rk_ordinal", lambda f, t: t.sort("id").select(f.col("v").rank("ordinal").alias("r")), ordered_equal),
        Check("rk_diff1", lambda f, t: t.sort("id").select(f.col("v").diff().alias("r")), ordered_equal),
        Check("rk_diff2", lambda f, t: t.sort("id").select(f.col("v").diff(2).alias("r")), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["rk_in"])
def rk_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/rk_in@NEW"], output_tables=CASE.output_names)
def rk_tfr(
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
def rk_sub(
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
