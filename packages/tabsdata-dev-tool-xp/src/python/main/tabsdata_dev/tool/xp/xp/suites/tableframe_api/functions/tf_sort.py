#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.sort — ascending, descending, nulls_last, and multi-column.

Order-sensitive, so every check verifies with ordered_equal; the sort keys are
unique so no tie makes the result ambiguous."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal

_INPUT = pl.DataFrame({"k": [3, 1, 2, 4], "n": [10, None, 30, 20]})
CASE = TFCase(
    inputs={"so_in": _INPUT},
    checks=[
        Check("so_asc", lambda f, t: t.sort("k"), ordered_equal),
        Check("so_desc", lambda f, t: t.sort("k", descending=True), ordered_equal),
        Check("so_nulls_last", lambda f, t: t.sort("n", nulls_last=True), ordered_equal),
        Check("so_multi", lambda f, t: t.sort(["k", "n"]), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["so_in"])
def so_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/so_in@NEW"], output_tables=CASE.output_names)
def so_tfr(
    t: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def so_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
