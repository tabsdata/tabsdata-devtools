#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.group_by(...) reduction shortcuts that are SAFE on a TableFrame:
count / len.

The value-reducing shortcuts (sum / min / max / mean / median / n_unique) are NOT
tested here: the shortcut reduces EVERY column of the frame, including the hidden
``$TD.*`` system columns. Through the storage round-trip one of those is a
``list[binary]`` column (plus a string one), which those reductions cannot handle
— the transformer builds a valid lazy plan that then raises at WRITE time
(``min operation not supported for dtype list[binary]``, etc.), stalling the
transaction. (This does not show up offline: ``from_polars`` builds different,
reducible system columns than storage does.) Column reductions must go through
``agg(col(...).<reduction>())`` — see tf_group_by_agg — which touches only the
named column. ``count()`` / ``len()`` are safe because they count rows rather than
reducing column values."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"k": ["x", "x", "y", "y", "z"], "v": [1, 2, 3, 4, 5]})
CASE = TFCase(
    inputs={"gbr_in": _INPUT},
    checks=[
        Check("gbr_count", lambda f, t: t.group_by("k").count(), unordered_equal),
        Check("gbr_len", lambda f, t: t.group_by("k").len(), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["gbr_in"])
def gbr_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/gbr_in@NEW"], output_tables=CASE.output_names)
def gbr_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def gbr_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
