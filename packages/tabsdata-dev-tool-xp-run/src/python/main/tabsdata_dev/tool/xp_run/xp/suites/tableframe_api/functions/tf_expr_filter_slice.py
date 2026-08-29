#
# Copyright 2026 Tabsdata Inc.
#
"""Expr.filter and Expr.slice — predicate-filtered aggregation input and positional expr slice."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal

_INPUT = pl.DataFrame({"id": [1, 2, 3, 4], "g": ["x", "y", "x", "y"], "v": [10, 20, 30, 40]})
CASE = TFCase(
    inputs={"ef_in": _INPUT},
    checks=[
        Check("ef_filter", lambda f, t: t.select(f.col("v").filter(f.col("g") == "x").alias("r")), unordered_equal),
        Check("ef_slice", lambda f, t: t.sort("id").select(f.col("v").slice(1, 2).alias("r")), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ef_in"])
def ef_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ef_in@NEW"], output_tables=CASE.output_names)
def ef_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ef_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
