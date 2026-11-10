#
# Copyright 2026 Tabsdata Inc.
#
"""Expr hyperbolic methods — sinh/cosh/tanh, inverses arcsinh/arccosh/arctanh, and degrees/radians."""
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

_INPUT = pl.DataFrame({"x": [0.2, 0.5, 0.8], "g": [1.5, 2.0, 3.0], "deg": [0.0, 90.0, 180.0]})
CASE = TFCase(
    inputs={"hy_in": _INPUT},
    checks=[
        Check("hy_sinh", lambda f, t: t.select(f.col("x").sinh().alias("r")), unordered_equal),
        Check("hy_cosh", lambda f, t: t.select(f.col("x").cosh().alias("r")), unordered_equal),
        Check("hy_tanh", lambda f, t: t.select(f.col("x").tanh().alias("r")), unordered_equal),
        Check("hy_arcsinh", lambda f, t: t.select(f.col("x").arcsinh().alias("r")), unordered_equal),
        Check("hy_arccosh", lambda f, t: t.select(f.col("g").arccosh().alias("r")), unordered_equal),
        Check("hy_arctanh", lambda f, t: t.select(f.col("x").arctanh().alias("r")), unordered_equal),
        Check("hy_degrees", lambda f, t: t.select(f.col("x").degrees().alias("r")), unordered_equal),
        Check("hy_radians", lambda f, t: t.select(f.col("deg").radians().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["hy_in"])
def hy_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/hy_in@NEW"], output_tables=CASE.output_names)
def hy_tfr(
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
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def hy_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7])
    return TableFrame.empty()
