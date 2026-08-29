#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime conversion — dt.to_string/strftime/epoch/timestamp/cast_time_unit."""
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
    inputs={"dv_in": _INPUT},
    checks=[
        Check("dv_to_string", lambda f, t: t.select(f.col("ts").dt.to_string("%Y-%m-%d").alias("r")), unordered_equal),
        Check("dv_strftime", lambda f, t: t.select(f.col("ts").dt.strftime("%H:%M").alias("r")), unordered_equal),
        Check("dv_epoch", lambda f, t: t.select(f.col("ts").dt.epoch("s").alias("r")), unordered_equal),
        Check("dv_timestamp", lambda f, t: t.select(f.col("ts").dt.timestamp("ms").alias("r")), unordered_equal),
        Check("dv_cast_unit", lambda f, t: t.select(f.col("ts").dt.cast_time_unit("ms").alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dv_in"])
def dv_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dv_in@NEW"], output_tables=CASE.output_names)
def dv_tfr(
    t: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dv_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
