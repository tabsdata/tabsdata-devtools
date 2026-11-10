#
# Copyright 2026 Tabsdata Inc.
#
"""Expr membership/range — is_in and is_between across all closed variants."""
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

_INPUT = pl.DataFrame({"a": [1, 2, 3, 4, 5]})
CASE = TFCase(
    inputs={"ib_in": _INPUT},
    checks=[
        Check("ib_isin", lambda f, t: t.select(f.col("a").is_in([2, 4]).alias("r")), unordered_equal),
        Check("ib_between_both", lambda f, t: t.select(f.col("a").is_between(2, 4).alias("r")), unordered_equal),
        Check("ib_between_left", lambda f, t: t.select(f.col("a").is_between(2, 4, closed="left").alias("r")), unordered_equal),
        Check("ib_between_right", lambda f, t: t.select(f.col("a").is_between(2, 4, closed="right").alias("r")), unordered_equal),
        Check("ib_between_none", lambda f, t: t.select(f.col("a").is_between(2, 4, closed="none").alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ib_in"])
def ib_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ib_in@NEW"], output_tables=CASE.output_names)
def ib_tfr(
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
def ib_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
