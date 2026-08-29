#
# Copyright 2026 Tabsdata Inc.
#
"""Expr boolean operators — ``& | ^ ~`` producing boolean columns."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"p": [True, True, False, False], "q": [True, False, True, False]})
CASE = TFCase(
    inputs={"bo_in": _INPUT},
    checks=[
        Check("bo_and", lambda f, t: t.select((f.col("p") & f.col("q")).alias("r")), unordered_equal),
        Check("bo_or", lambda f, t: t.select((f.col("p") | f.col("q")).alias("r")), unordered_equal),
        Check("bo_xor", lambda f, t: t.select((f.col("p") ^ f.col("q")).alias("r")), unordered_equal),
        Check("bo_not", lambda f, t: t.select((~f.col("p")).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["bo_in"])
def bo_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/bo_in@NEW"], output_tables=CASE.output_names)
def bo_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def bo_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
