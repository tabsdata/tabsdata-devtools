#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime components — dt.weekday/ordinal_day/iso_year/millennium/century/millisecond/microsecond/nanosecond."""
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
    inputs={"dc2_in": _INPUT},
    checks=[
        Check("dc2_weekday", lambda f, t: t.select(f.col("ts").dt.weekday().alias("r")), unordered_equal),
        Check("dc2_ordinal", lambda f, t: t.select(f.col("ts").dt.ordinal_day().alias("r")), unordered_equal),
        Check("dc2_isoyear", lambda f, t: t.select(f.col("ts").dt.iso_year().alias("r")), unordered_equal),
        Check("dc2_millennium", lambda f, t: t.select(f.col("ts").dt.millennium().alias("r")), unordered_equal),
        Check("dc2_century", lambda f, t: t.select(f.col("ts").dt.century().alias("r")), unordered_equal),
        Check("dc2_ms", lambda f, t: t.select(f.col("ts").dt.millisecond().alias("r")), unordered_equal),
        Check("dc2_us", lambda f, t: t.select(f.col("ts").dt.microsecond().alias("r")), unordered_equal),
        Check("dc2_ns", lambda f, t: t.select(f.col("ts").dt.nanosecond().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dc2_in"])
def dc2_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dc2_in@NEW"], output_tables=CASE.output_names)
def dc2_tfr(
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
def dc2_sub(
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
