#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.drop_nulls — across all columns and restricted to a subset."""
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

_INPUT = pl.DataFrame({"a": [1, None, 3], "b": [4, 5, None]})
CASE = TFCase(
    inputs={"dn_in": _INPUT},
    checks=[
        Check("dn_all", lambda f, t: t.drop_nulls(), unordered_equal),
        Check("dn_subset", lambda f, t: t.drop_nulls(subset="a"), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["dn_in"])
def dn_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/dn_in@NEW"], output_tables=CASE.output_names)
def dn_tfr(t_versions: TableFramesSpec) -> tuple[TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def dn_sub(c0: TableFrameSpec, c1: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1])
    return TableFrame.empty()
