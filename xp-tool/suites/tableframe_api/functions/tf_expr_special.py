#
# Copyright 2026 Tabsdata Inc.
#
"""Expr special functions — erf/erfc."""
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

_INPUT = pl.DataFrame({"x": [-1.0, 0.0, 0.5, 2.0]})
CASE = TFCase(
    inputs={"sf_in": _INPUT},
    checks=[
        Check("sf_erf", lambda f, t: t.select(f.col("x").erf().alias("r")), unordered_equal),
        Check("sf_erfc", lambda f, t: t.select(f.col("x").erfc().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sf_in"])
def sf_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sf_in@NEW"], output_tables=CASE.output_names)
def sf_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sf_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
