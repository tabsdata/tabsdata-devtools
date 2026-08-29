#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str slicing — ``slice`` (offset, offset+length) and ``head`` / ``tail`` (leading/trailing chars)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"s": ["abcdef", "ghijkl", "mnopqr"]})
CASE = TFCase(
    inputs={"ss_in": _INPUT},
    checks=[
        Check("ss_slice_off", lambda f, t: t.select(f.col("s").str.slice(2).alias("r")), unordered_equal),
        Check("ss_slice_len", lambda f, t: t.select(f.col("s").str.slice(1, 3).alias("r")), unordered_equal),
        Check("ss_head", lambda f, t: t.select(f.col("s").str.head(2).alias("r")), unordered_equal),
        Check("ss_tail", lambda f, t: t.select(f.col("s").str.tail(2).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ss_in"])
def ss_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ss_in@NEW"], output_tables=CASE.output_names)
def ss_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ss_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
