#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.unnest — expand one struct column, and several struct columns at
once, into their fields."""
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

_INPUT = pl.DataFrame(
    {
        "s": [{"x": 1, "y": 2}, {"x": 3, "y": 4}, {"x": 5, "y": 6}],
        "t": [{"m": 7}, {"m": 8}, {"m": 9}],
    }
)
CASE = TFCase(
    inputs={"uns_in": _INPUT},
    checks=[
        Check("uns_one", lambda f, t: t.unnest("s"), unordered_equal),
        Check("uns_two", lambda f, t: t.unnest("s", "t"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["uns_in"])
def uns_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/uns_in@NEW"], output_tables=CASE.output_names)
def uns_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def uns_sub(a: TableFrameSpec, b: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([a, b])
    return TableFrame.empty()
