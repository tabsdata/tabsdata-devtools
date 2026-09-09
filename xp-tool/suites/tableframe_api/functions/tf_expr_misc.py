#
# Copyright 2026 Tabsdata Inc.
#
"""Expr misc — ``hash alias cast shrink_dtype``."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3, 4]})
CASE = TFCase(
    inputs={"ms_in": _INPUT},
    checks=[
        Check("ms_hash", lambda f, t: t.select(f.col("a").hash(seed=0).alias("r")), unordered_equal),
        Check("ms_alias", lambda f, t: t.select(f.col("a").alias("r")), unordered_equal),
        Check("ms_cast", lambda f, t: t.select(f.col("a").cast(pl.Float64).alias("r")), unordered_equal),
        Check("ms_shrink", lambda f, t: t.select(f.col("a").shrink_dtype().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ms_in"])
def ms_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ms_in@NEW"], output_tables=CASE.output_names)
def ms_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ms_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
