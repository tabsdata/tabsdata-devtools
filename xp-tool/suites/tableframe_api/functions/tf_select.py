#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.select — by name, by expression with alias, and by several names."""
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

_INPUT = pl.DataFrame({"a": [3, 1, 2], "b": ["x", "y", "z"]})
CASE = TFCase(
    inputs={"select_in": _INPUT},
    checks=[
        Check("select_name", lambda f, t: t.select("a"), unordered_equal),
        Check("select_alias", lambda f, t: t.select((f.col("a") * 2).alias("a2")), unordered_equal),
        Check("select_multi", lambda f, t: t.select("a", "b"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["select_in"])
def select_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/select_in@NEW"], output_tables=CASE.output_names)
def select_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def select_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
