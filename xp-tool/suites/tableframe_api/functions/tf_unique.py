#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.unique — subset duplicate removal.

The no-subset forms (``unique()`` and ``unique(keep="none")``) diverge from polars
(they dedup over the hidden $TD.* system columns, so nothing is removed); they are
cataloged in the ``failing`` sub-suite and should be reintroduced here as passing
tests once fixed in tabsdatak."""
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

_INPUT = pl.DataFrame({"a": [1, 1, 2, 3], "b": [10, 10, 20, 30]})
CASE = TFCase(
    inputs={"un_in": _INPUT},
    checks=[
        Check("un_subset", lambda f, t: t.unique(subset="a"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["un_in"])
def un_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/un_in@NEW"], output_tables=CASE.output_names)
def un_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def un_sub(c0: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0])
    return TableFrame.empty()
