#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.clear — an empty same-schema frame and an n-row null frame."""
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

_INPUT = pl.DataFrame({"a": [1, 2, 3], "b": [4, 5, 6]})
CASE = TFCase(
    inputs={"cl_in": _INPUT},
    checks=[
        Check("cl_zero", lambda f, t: t.clear(), unordered_equal),
        Check("cl_n", lambda f, t: t.clear(2), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["cl_in"])
def cl_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/cl_in@NEW"], output_tables=CASE.output_names)
def cl_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def cl_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
