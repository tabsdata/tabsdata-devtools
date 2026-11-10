#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.__getitem__ — row slicing (``t[a:b]``).

The TableFrame is lazy, so only slicing is supported (column subscription like
``t[["a"]]`` raises); slices are order-sensitive, so each sorts on a unique key
first and verifies with ordered_equal."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import concat

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal

_INPUT = pl.DataFrame({"id": [3, 1, 2, 4, 5], "v": [30, 10, 20, 40, 50]})
CASE = TFCase(
    inputs={"gi_in": _INPUT},
    checks=[
        Check("gi_head2", lambda f, t: t.sort("id")[:2], ordered_equal),
        Check("gi_mid", lambda f, t: t.sort("id")[1:3], ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["gi_in"])
def gi_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/gi_in@NEW"], output_tables=CASE.output_names)
def gi_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def gi_sub(a: TableFrameSpec, b: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([a, b])
    return TableFrame.empty()
