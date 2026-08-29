#
# Copyright 2026 Tabsdata Inc.
#
"""functions.concat — vertical / diagonal stacking, plus the tabsdata-specific
None/empty contract that polars cannot express:

    concat(None)        -> None
    concat([tf, None])  -> concat([tf])   (None elements are skipped)
    concat([])          -> None

Those three use an ``expected`` override (polars would raise on None / []). They
encode the INTENDED behaviour: today tabsdatak's concat forwards to ``pl.concat``
and raises on all three, so they are RED until concat special-cases None/empty."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_LEFT = pl.DataFrame({"x": [1, 2], "y": ["a", "b"]})
_RIGHT = pl.DataFrame({"x": [3, 4], "y": ["c", "d"]})
CASE = TFCase(
    inputs={"cc_left": _LEFT, "cc_right": _RIGHT},
    checks=[
        Check("cc_vertical", lambda f, l, r: f.concat([l, r], how="vertical"), unordered_equal),
        Check("cc_diagonal", lambda f, l, r: f.concat([l, r], how="diagonal"), unordered_equal),
        # concat(None) -> None
        Check("cc_none", lambda f, l, r: f.concat(None), unordered_equal, expected=lambda l, r: None),
        # concat([tf, None]) -> concat([tf]): None elements are dropped
        Check("cc_skip_none", lambda f, l, r: f.concat([l, None]), unordered_equal, expected=lambda l, r: pl.concat([l])),
        # concat([]) -> None
        Check("cc_empty", lambda f, l, r: f.concat([]), unordered_equal, expected=lambda l, r: None),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["cc_left", "cc_right"])
def cc_pub(
    left: TableFrameSpec, right: TableFrameSpec
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (left, right)


@transformer(
    input_tables=[f"{SRC}/cc_left@NEW", f"{SRC}/cc_right@HEAD"],
    output_tables=CASE.output_names,
)
def cc_tfr(
    left: TableFrameSpec, right: TableFrameSpec
) -> tuple[
    TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec
]:
    return CASE.transform(left, right)


@subscriber(
    destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names]
)
def cc_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
