#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str stripping — ``strip_chars`` / ``strip_chars_start`` / ``strip_chars_end`` / ``strip_prefix`` / ``strip_suffix``."""
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

_INPUT = pl.DataFrame({"ws": ["  ab  ", "  cd  ", "  ef  "], "px": ["preA", "preB", "xxC"]})
CASE = TFCase(
    inputs={"sp_in": _INPUT},
    checks=[
        Check("sp_strip", lambda f, t: t.select(f.col("ws").str.strip_chars().alias("r")), unordered_equal),
        Check("sp_start", lambda f, t: t.select(f.col("ws").str.strip_chars_start().alias("r")), unordered_equal),
        Check("sp_end", lambda f, t: t.select(f.col("ws").str.strip_chars_end().alias("r")), unordered_equal),
        Check("sp_prefix", lambda f, t: t.select(f.col("px").str.strip_prefix("pre").alias("r")), unordered_equal),
        Check("sp_suffix", lambda f, t: t.select(f.col("px").str.strip_suffix("A").alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sp_in"])
def sp_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sp_in@NEW"], output_tables=CASE.output_names)
def sp_tfr(
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
def sp_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
