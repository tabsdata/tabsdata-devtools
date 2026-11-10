#
# Copyright 2026 Tabsdata Inc.
#
"""Expr unary operators — negation ``-``, unary plus ``+`` and builtin ``abs``."""
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

_INPUT = pl.DataFrame({"a": [-5, 2, -8, 3]})
CASE = TFCase(
    inputs={"uy_in": _INPUT},
    checks=[
        Check("uy_neg", lambda f, t: t.select((-f.col("a")).alias("r")), unordered_equal),
        Check("uy_pos", lambda f, t: t.select((+f.col("a")).alias("r")), unordered_equal),
        Check("uy_abs", lambda f, t: t.select(abs(f.col("a")).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["uy_in"])
def uy_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/uy_in@NEW"], output_tables=CASE.output_names)
def uy_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def uy_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
