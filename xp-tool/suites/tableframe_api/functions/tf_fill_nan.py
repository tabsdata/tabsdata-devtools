#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.fill_nan — replacing NaN entries with a literal value."""
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

_INPUT = pl.DataFrame({"a": [1.0, float("nan"), 3.0]})
CASE = TFCase(
    inputs={"fnan_in": _INPUT},
    checks=[
        Check("fnan_zero", lambda f, t: t.fill_nan(0.0), unordered_equal),
        Check("fnan_neg", lambda f, t: t.fill_nan(-1.0), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["fnan_in"])
def fnan_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/fnan_in@NEW"], output_tables=CASE.output_names)
def fnan_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def fnan_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
