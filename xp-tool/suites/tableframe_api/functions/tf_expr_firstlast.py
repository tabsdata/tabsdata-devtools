#
# Copyright 2026 Tabsdata Inc.
#
"""Expr first/last/is_unique — sorted by a unique id, so order-sensitive."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal

_INPUT = pl.DataFrame({"id": [3, 1, 2], "v": [30, 10, 20]})
CASE = TFCase(
    inputs={"fl_in": _INPUT},
    checks=[
        Check("fl_first", lambda f, t: t.sort("id").select(f.col("v").first().alias("r")), ordered_equal),
        Check("fl_last", lambda f, t: t.sort("id").select(f.col("v").last().alias("r")), ordered_equal),
        Check("fl_is_unique", lambda f, t: t.sort("id").select(f.col("v").is_unique().alias("r")), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["fl_in"])
def fl_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/fl_in@NEW"], output_tables=CASE.output_names)
def fl_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def fl_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
