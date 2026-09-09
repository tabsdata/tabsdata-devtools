#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.select — multi-output: one input projected into two result tables."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [3, 1, 2], "b": ["x", "y", "z"]})
CASE = TFCase(
    inputs={"split_in": _INPUT},
    checks=[
        Check("split_a", lambda f, t: t.select("a"), unordered_equal),
        Check("split_b", lambda f, t: t.select("b"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["split_in"])
def split_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/split_in@NEW"], output_tables=CASE.output_names)
def split_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def split_sub(a: TableFrameSpec, b: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([a, b])
    return TableFrame.empty()
