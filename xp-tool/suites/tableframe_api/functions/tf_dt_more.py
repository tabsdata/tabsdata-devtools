#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime extras — dt.add_business_days / combine / replace_time_zone(None)."""
from __future__ import annotations

import polars as pl
from datetime import datetime, time
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
    inputs={"dmr_in": _INPUT},
    checks=[
        Check("dmr_add_bdays", lambda f, t: t.select(f.col("ts").dt.add_business_days(3).alias("r")), unordered_equal),
        Check("dmr_combine", lambda f, t: t.select(f.col("ts").dt.combine(time(6, 30)).alias("r")), unordered_equal),
        Check("dmr_naive", lambda f, t: t.select(f.col("ts").dt.replace_time_zone(None).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dmr_in"])
def dmr_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dmr_in@NEW"], output_tables=CASE.output_names)
def dmr_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dmr_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
