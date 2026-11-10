#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str padding — ``pad_start`` / ``pad_end`` (custom fill char) and ``zfill`` (zero-fill)."""
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

_INPUT = pl.DataFrame({"s": ["1", "22", "333"]})
CASE = TFCase(
    inputs={"sd_in": _INPUT},
    checks=[
        Check("sd_pad_start", lambda f, t: t.select(f.col("s").str.pad_start(4, "0").alias("r")), unordered_equal),
        Check("sd_pad_end", lambda f, t: t.select(f.col("s").str.pad_end(4, "-").alias("r")), unordered_equal),
        Check("sd_zfill", lambda f, t: t.select(f.col("s").str.zfill(4).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sd_in"])
def sd_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sd_in@NEW"], output_tables=CASE.output_names)
def sd_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sd_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
