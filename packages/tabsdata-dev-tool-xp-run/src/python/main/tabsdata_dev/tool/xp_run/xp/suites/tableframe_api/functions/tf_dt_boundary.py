#
# Copyright 2026 Tabsdata Inc.
#
"""Expr datetime boundaries — dt.month_start/month_end/truncate/offset_by/replace."""
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
    inputs={"db_in": _INPUT},
    checks=[
        Check("db_month_start", lambda f, t: t.select(f.col("ts").dt.month_start().alias("r")), unordered_equal),
        Check("db_month_end", lambda f, t: t.select(f.col("ts").dt.month_end().alias("r")), unordered_equal),
        Check("db_truncate", lambda f, t: t.select(f.col("ts").dt.truncate("1mo").alias("r")), unordered_equal),
        Check("db_offset", lambda f, t: t.select(f.col("ts").dt.offset_by("1d").alias("r")), unordered_equal),
        Check("db_replace", lambda f, t: t.select(f.col("ts").dt.replace(day=1).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["db_in"])
def db_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/db_in@NEW"], output_tables=CASE.output_names)
def db_tfr(
    t: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def db_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
