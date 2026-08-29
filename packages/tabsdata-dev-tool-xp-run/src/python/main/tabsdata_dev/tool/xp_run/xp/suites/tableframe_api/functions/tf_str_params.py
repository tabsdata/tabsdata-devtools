#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str deeper params — to_integer(base) / replace(n) / to_datetime(fmt, time_zone)."""
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
        "h": ["ff", "10", "2a"],
        "dt": ["2021-01-01 10:00:00", "2021-06-15 12:30:00", "2021-12-31 23:59:59"],
        "s": ["aXaXa", "bYb", "cZc"],
    }
)
CASE = TFCase(
    inputs={"spm_in": _INPUT},
    checks=[
        Check("spm_to_int_base", lambda f, t: t.select(f.col("h").str.to_integer(base=16).alias("r")), unordered_equal),
        Check("spm_replace_n2", lambda f, t: t.select(f.col("s").str.replace("a", "_", n=2).alias("r")), unordered_equal),
        Check("spm_to_datetime_fmt", lambda f, t: t.select(f.col("dt").str.to_datetime("%Y-%m-%d %H:%M:%S").alias("r")), unordered_equal),
        Check("spm_to_datetime_tz", lambda f, t: t.select(f.col("dt").str.to_datetime("%Y-%m-%d %H:%M:%S", time_zone="UTC").alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["spm_in"])
def spm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/spm_in@NEW"], output_tables=CASE.output_names)
def spm_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def spm_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
