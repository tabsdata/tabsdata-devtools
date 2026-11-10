#
# Copyright 2026 Tabsdata Inc.
#
"""Expr timezone ops — dt.replace_time_zone/convert_time_zone/base_utc_offset/dst_offset."""
from __future__ import annotations

import polars as pl
from datetime import datetime
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

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
    inputs={"dz_in": _INPUT},
    checks=[
        Check("dz_replace_tz", lambda f, t: t.select(f.col("ts").dt.replace_time_zone("UTC").alias("r")), unordered_equal),
        Check("dz_convert_tz", lambda f, t: t.select(f.col("ts").dt.replace_time_zone("UTC").dt.convert_time_zone("America/New_York").alias("r")), unordered_equal),
        Check("dz_base_offset", lambda f, t: t.select(f.col("ts").dt.replace_time_zone("UTC").dt.base_utc_offset().alias("r")), unordered_equal),
        Check("dz_dst_offset", lambda f, t: t.select(f.col("ts").dt.replace_time_zone("UTC").dt.dst_offset().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dz_in"])
def dz_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dz_in@NEW"], output_tables=CASE.output_names)
def dz_tfr(
    t_versions: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dz_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
