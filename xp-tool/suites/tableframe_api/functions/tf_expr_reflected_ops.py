#
# Copyright 2026 Tabsdata Inc.
#
"""Expr reflected operators — right-hand ``+ - * / // % **`` and ``& | ^``."""
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

_INPUT = pl.DataFrame({"a": [6, 7, 8, 9], "p": [True, False, True, False]})
CASE = TFCase(
    inputs={"rf_in": _INPUT},
    checks=[
        Check("rf_radd", lambda f, t: t.select((5 + f.col("a")).alias("r")), unordered_equal),
        Check("rf_rsub", lambda f, t: t.select((100 - f.col("a")).alias("r")), unordered_equal),
        Check("rf_rmul", lambda f, t: t.select((3 * f.col("a")).alias("r")), unordered_equal),
        Check("rf_rtruediv", lambda f, t: t.select((60 / f.col("a")).alias("r")), unordered_equal),
        Check("rf_rfloordiv", lambda f, t: t.select((100 // f.col("a")).alias("r")), unordered_equal),
        Check("rf_rmod", lambda f, t: t.select((100 % f.col("a")).alias("r")), unordered_equal),
        Check("rf_rpow", lambda f, t: t.select((2 ** f.col("a")).alias("r")), unordered_equal),
        Check("rf_rand", lambda f, t: t.select((True & f.col("p")).alias("r")), unordered_equal),
        Check("rf_ror", lambda f, t: t.select((True | f.col("p")).alias("r")), unordered_equal),
        Check("rf_rxor", lambda f, t: t.select((True ^ f.col("p")).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["rf_in"])
def rf_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/rf_in@NEW"], output_tables=CASE.output_names)
def rf_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def rf_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
    c8: TableFrameSpec,
    c9: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7, c8, c9])
    return TableFrame.empty()
