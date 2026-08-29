#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.drop_nans — across all columns and restricted to a subset."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1.0, float("nan"), 3.0], "b": [4.0, 5.0, float("nan")]})
CASE = TFCase(
    inputs={"dnan_in": _INPUT},
    checks=[
        Check("dnan_all", lambda f, t: t.drop_nans(), unordered_equal),
        Check("dnan_subset", lambda f, t: t.drop_nans(subset="a"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dnan_in"])
def dnan_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dnan_in@NEW"], output_tables=CASE.output_names)
def dnan_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dnan_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
