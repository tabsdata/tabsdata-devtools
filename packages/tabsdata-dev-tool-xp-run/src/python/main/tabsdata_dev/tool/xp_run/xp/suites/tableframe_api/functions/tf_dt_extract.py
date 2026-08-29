#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime extraction — dt.date/time/is_leap_year."""
from __future__ import annotations

import polars as pl
from datetime import datetime
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame(
    {
        "ts": [
            datetime(2021, 1, 5, 10, 30, 15),
            datetime(2021, 6, 15, 12, 0, 0),
            datetime(2020, 12, 31, 23, 59, 59),
        ]
    }
)
CASE = TFCase(
    inputs={"dx_in": _INPUT},
    checks=[
        Check("dx_date", lambda f, t: t.select(f.col("ts").dt.date().alias("r")), unordered_equal),
        Check("dx_time", lambda f, t: t.select(f.col("ts").dt.time().alias("r")), unordered_equal),
        Check("dx_isleap", lambda f, t: t.select(f.col("ts").dt.is_leap_year().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dx_in"])
def dx_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dx_in@NEW"], output_tables=CASE.output_names)
def dx_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dx_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
