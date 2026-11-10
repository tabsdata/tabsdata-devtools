#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str length — ``len_bytes`` (UTF-8 byte count) and ``len_chars`` (code points)."""
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

_INPUT = pl.DataFrame({"s": ["a", "bb", "ccc", "déf"]})
CASE = TFCase(
    inputs={"sn_in": _INPUT},
    checks=[
        Check("sn_bytes", lambda f, t: t.select(f.col("s").str.len_bytes().alias("r")), unordered_equal),
        Check("sn_chars", lambda f, t: t.select(f.col("s").str.len_chars().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sn_in"])
def sn_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sn_in@NEW"], output_tables=CASE.output_names)
def sn_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sn_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
