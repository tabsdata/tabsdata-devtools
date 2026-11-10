#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.group_by(...).agg — sum / mean / min / max / count / n_unique
aggregations keyed by a group column."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"k": ["x", "x", "y", "y", "z"], "v": [1, 2, 3, 4, 5]})
CASE = TFCase(
    inputs={"gba_in": _INPUT},
    checks=[
        Check("gba_sum", lambda f, t: t.group_by("k").agg(f.col("v").sum().alias("s")), unordered_equal),
        Check("gba_mean", lambda f, t: t.group_by("k").agg(f.col("v").mean().alias("m")), unordered_equal),
        Check("gba_min", lambda f, t: t.group_by("k").agg(f.col("v").min().alias("mn")), unordered_equal),
        Check("gba_max", lambda f, t: t.group_by("k").agg(f.col("v").max().alias("mx")), unordered_equal),
        Check("gba_count", lambda f, t: t.group_by("k").agg(f.col("v").count().alias("c")), unordered_equal),
        Check("gba_nunique", lambda f, t: t.group_by("k").agg(f.col("v").n_unique().alias("nu")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["gba_in"])
def gba_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/gba_in@NEW"], output_tables=CASE.output_names)
def gba_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
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
def gba_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
