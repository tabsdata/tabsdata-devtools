#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame deeper params — cast(strict) / unique(keep,maintain_order) / fill_null(limit) / sort(descending,nulls_last)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal

_INPUT = pl.DataFrame(
    {
        "id": [1, 2, 3, 4],
        "k": ["x", "x", "y", "z"],
        "v": [10, None, None, 40],
        "n": [3, 1, None, 2],
    }
)
CASE = TFCase(
    inputs={"fp_in": _INPUT},
    checks=[
        Check("fp_cast_nonstrict", lambda f, t: t.with_columns(f.col("id").cast(pl.Int8, strict=False).alias("r")), unordered_equal),
        Check("fp_unique_first", lambda f, t: t.sort("id").unique(subset="k", keep="first", maintain_order=True), ordered_equal),
        Check("fp_unique_last", lambda f, t: t.sort("id").unique(subset="k", keep="last", maintain_order=True), ordered_equal),
        Check("fp_fill_limit", lambda f, t: t.sort("id").fill_null(strategy="forward", limit=1), ordered_equal),
        Check("fp_sort_desc_multi", lambda f, t: t.sort(["k", "id"], descending=[True, False]), ordered_equal),
        Check("fp_sort_nulls_last", lambda f, t: t.sort("n", nulls_last=True), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["fp_in"])
def fp_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/fp_in@NEW"], output_tables=CASE.output_names)
def fp_tfr(
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
def fp_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
