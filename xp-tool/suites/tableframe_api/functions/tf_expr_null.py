#
# Copyright 2026 Tabsdata Inc.
#
"""Expr null handling — ``is_null is_not_null fill_null``."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, None, 3]})
CASE = TFCase(
    inputs={"nl_in": _INPUT},
    checks=[
        Check("nl_is_null", lambda f, t: t.select(f.col("a").is_null().alias("r")), unordered_equal),
        Check("nl_is_not_null", lambda f, t: t.select(f.col("a").is_not_null().alias("r")), unordered_equal),
        Check("nl_fill", lambda f, t: t.select(f.col("a").fill_null(0).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["nl_in"])
def nl_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/nl_in@NEW"], output_tables=CASE.output_names)
def nl_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def nl_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
