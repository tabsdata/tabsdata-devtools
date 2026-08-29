#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.drop — one column, several columns, and a list of columns."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6], "c": [7, 8, 9]})
CASE = TFCase(
    inputs={"dr_in": _INPUT},
    checks=[
        Check("dr_one", lambda f, t: t.drop("a"), unordered_equal),
        Check("dr_multi", lambda f, t: t.drop("a", "b"), unordered_equal),
        Check("dr_list", lambda f, t: t.drop(["b", "c"]), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dr_in"])
def dr_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dr_in@NEW"], output_tables=CASE.output_names)
def dr_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dr_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
