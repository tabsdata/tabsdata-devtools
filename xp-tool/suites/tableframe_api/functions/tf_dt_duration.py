#
# Copyright 2026 Tabsdata Inc.
#
"""Expr duration totals — dt.total_days/hours/minutes/seconds/milliseconds/microseconds/nanoseconds."""
from __future__ import annotations

import polars as pl
from datetime import timedelta
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame(
    {"dur": [timedelta(days=1, hours=2), timedelta(hours=5), timedelta(minutes=90)]}
)
CASE = TFCase(
    inputs={"dd_in": _INPUT},
    checks=[
        Check("dd_days", lambda f, t: t.select(f.col("dur").dt.total_days().alias("r")), unordered_equal),
        Check("dd_hours", lambda f, t: t.select(f.col("dur").dt.total_hours().alias("r")), unordered_equal),
        Check("dd_minutes", lambda f, t: t.select(f.col("dur").dt.total_minutes().alias("r")), unordered_equal),
        Check("dd_seconds", lambda f, t: t.select(f.col("dur").dt.total_seconds().alias("r")), unordered_equal),
        Check("dd_ms", lambda f, t: t.select(f.col("dur").dt.total_milliseconds().alias("r")), unordered_equal),
        Check("dd_us", lambda f, t: t.select(f.col("dur").dt.total_microseconds().alias("r")), unordered_equal),
        Check("dd_ns", lambda f, t: t.select(f.col("dur").dt.total_nanoseconds().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dd_in"])
def dd_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dd_in@NEW"], output_tables=CASE.output_names)
def dd_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
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
def dd_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6])
    return TableFrame.empty()
