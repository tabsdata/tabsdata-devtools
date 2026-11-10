#
# Copyright 2026 Tabsdata Inc.
#
"""Expr boolean methods — ``and_ or_ xor not_`` producing boolean columns."""
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

_INPUT = pl.DataFrame({"p": [True, True, False, False], "q": [True, False, True, False]})
CASE = TFCase(
    inputs={"bm_in": _INPUT},
    checks=[
        Check("bm_and", lambda f, t: t.select(f.col("p").and_(f.col("q")).alias("r")), unordered_equal),
        Check("bm_or", lambda f, t: t.select(f.col("p").or_(f.col("q")).alias("r")), unordered_equal),
        Check("bm_xor", lambda f, t: t.select(f.col("p").xor(f.col("q")).alias("r")), unordered_equal),
        Check("bm_not", lambda f, t: t.select(f.col("p").not_().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["bm_in"])
def bm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/bm_in@NEW"], output_tables=CASE.output_names)
def bm_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def bm_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
