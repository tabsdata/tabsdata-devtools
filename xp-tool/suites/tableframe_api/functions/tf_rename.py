#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.rename — a single-key mapping and a multi-key mapping.

The callable form (``rename(<callable>)``) diverges from polars (it renames the
hidden $TD.* system columns too); it is cataloged in the ``failing`` sub-suite and
should be reintroduced here as a passing test once fixed in tabsdatak."""
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
    inputs={"rn_in": _INPUT},
    checks=[
        Check("rn_map", lambda f, t: t.rename({"a": "x"}), unordered_equal),
        Check("rn_multi", lambda f, t: t.rename({"a": "x", "b": "y"}), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["rn_in"])
def rn_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/rn_in@NEW"], output_tables=CASE.output_names)
def rn_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def rn_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
