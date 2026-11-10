#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.filter — single predicate, an AND of predicates, an is_in
predicate, and an equality **constraints** keyword."""
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

_INPUT = pl.DataFrame({"a": [1, 2, 3, 4, 5], "g": ["x", "x", "y", "y", "z"]})
CASE = TFCase(
    inputs={"flt_in": _INPUT},
    checks=[
        Check("flt_gt", lambda f, t: t.filter(f.col("a") > 2), unordered_equal),
        Check("flt_and", lambda f, t: t.filter((f.col("a") > 1) & (f.col("a") < 5)), unordered_equal),
        Check("flt_isin", lambda f, t: t.filter(f.col("g").is_in(["x", "y"])), unordered_equal),
        Check("flt_constraint", lambda f, t: t.filter(g="x"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["flt_in"])
def flt_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/flt_in@NEW"], output_tables=CASE.output_names)
def flt_tfr(
    t_versions: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def flt_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
