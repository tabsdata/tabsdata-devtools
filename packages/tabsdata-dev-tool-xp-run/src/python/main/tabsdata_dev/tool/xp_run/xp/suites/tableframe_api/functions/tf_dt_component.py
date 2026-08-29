#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime components — dt.year/month/day/hour/minute/second/quarter/week."""
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
    inputs={"dc_in": _INPUT},
    checks=[
        Check("dc_year", lambda f, t: t.select(f.col("ts").dt.year().alias("r")), unordered_equal),
        Check("dc_month", lambda f, t: t.select(f.col("ts").dt.month().alias("r")), unordered_equal),
        Check("dc_day", lambda f, t: t.select(f.col("ts").dt.day().alias("r")), unordered_equal),
        Check("dc_hour", lambda f, t: t.select(f.col("ts").dt.hour().alias("r")), unordered_equal),
        Check("dc_minute", lambda f, t: t.select(f.col("ts").dt.minute().alias("r")), unordered_equal),
        Check("dc_second", lambda f, t: t.select(f.col("ts").dt.second().alias("r")), unordered_equal),
        Check("dc_quarter", lambda f, t: t.select(f.col("ts").dt.quarter().alias("r")), unordered_equal),
        Check("dc_week", lambda f, t: t.select(f.col("ts").dt.week().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dc_in"])
def dc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dc_in@NEW"], output_tables=CASE.output_names)
def dc_tfr(
    t: TableFrameSpec,
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
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dc_sub(
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
