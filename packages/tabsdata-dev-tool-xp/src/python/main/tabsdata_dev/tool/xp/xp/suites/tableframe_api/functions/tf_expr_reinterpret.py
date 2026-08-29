#
# Copyright 2026 Tabsdata Inc.
#
"""Expr.reinterpret — reinterpret 64-bit integer bits as unsigned and as signed."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3, 4]})
CASE = TFCase(
    inputs={"ri_in": _INPUT},
    checks=[
        Check("ri_unsigned", lambda f, t: t.select(f.col("a").reinterpret(signed=False).alias("r")), unordered_equal),
        Check("ri_signed", lambda f, t: t.select(f.col("a").reinterpret(signed=True).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ri_in"])
def ri_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ri_in@NEW"], output_tables=CASE.output_names)
def ri_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ri_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
