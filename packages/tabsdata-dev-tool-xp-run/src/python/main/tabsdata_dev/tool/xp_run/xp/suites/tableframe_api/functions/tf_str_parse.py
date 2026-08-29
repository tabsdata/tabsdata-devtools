#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str parsing — ``to_integer`` / ``to_date`` / ``to_datetime`` / ``to_time`` conversions."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame(
    {
        "i": ["10", "20", "30"],
        "d": ["2021-01-01", "2021-06-15", "2021-12-31"],
        "dt": ["2021-01-01 10:00:00", "2021-06-15 12:30:00", "2021-12-31 23:59:59"],
        "t": ["10:00:00", "12:30:00", "23:59:59"],
    }
)
CASE = TFCase(
    inputs={"sq_in": _INPUT},
    checks=[
        Check("sq_to_integer", lambda f, t: t.select(f.col("i").str.to_integer().alias("r")), unordered_equal),
        Check("sq_to_date", lambda f, t: t.select(f.col("d").str.to_date().alias("r")), unordered_equal),
        Check("sq_to_datetime", lambda f, t: t.select(f.col("dt").str.to_datetime().alias("r")), unordered_equal),
        Check("sq_to_time", lambda f, t: t.select(f.col("t").str.to_time().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sq_in"])
def sq_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sq_in@NEW"], output_tables=CASE.output_names)
def sq_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sq_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
