#
# Copyright 2026 Tabsdata Inc.
#
"""Expr clip/sign/abs — clip both/lower/upper bounds, sign, abs."""
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

_INPUT = pl.DataFrame({"a": [-5, 2, 10, -1]})
CASE = TFCase(
    inputs={"cs_in": _INPUT},
    checks=[
        Check("cs_clip_both", lambda f, t: t.select(f.col("a").clip(0, 5).alias("r")), unordered_equal),
        Check("cs_clip_lo", lambda f, t: t.select(f.col("a").clip(0).alias("r")), unordered_equal),
        Check("cs_clip_hi", lambda f, t: t.select(f.col("a").clip(None, 5).alias("r")), unordered_equal),
        Check("cs_sign", lambda f, t: t.select(f.col("a").sign().alias("r")), unordered_equal),
        Check("cs_abs", lambda f, t: t.select(f.col("a").abs().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["cs_in"])
def cs_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/cs_in@NEW"], output_tables=CASE.output_names)
def cs_tfr(
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
def cs_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
