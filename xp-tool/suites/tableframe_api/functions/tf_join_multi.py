#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.join — multi-way chains (triple, quadruple) and joining against an
aggregated table (group_by(...).agg then join). Four input tables."""
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

_A = pl.DataFrame({"id": [1, 2, 3], "av": [10, 20, 30]})
_B = pl.DataFrame({"id": [1, 2, 3], "bv": [100, 200, 300]})
_C = pl.DataFrame({"id": [1, 2, 3], "cv": [1000, 2000, 3000]})
_E = pl.DataFrame({"id": [1, 1, 2, 2, 3], "amt": [5, 7, 10, 12, 15]})
CASE = TFCase(
    inputs={"jm_a": _A, "jm_b": _B, "jm_c": _C, "jm_e": _E},
    checks=[
        Check(
            "jm_triple",
            lambda f, a, b, c, e: a.join(b, on="id").join(c, on="id"),
            unordered_equal,
        ),
        Check(
            "jm_quad",
            lambda f, a, b, c, e: a.join(b, on="id")
            .join(c, on="id")
            .join(e.group_by("id").agg(f.col("amt").sum().alias("amt")), on="id"),
            unordered_equal,
        ),
        Check(
            "jm_agg",
            lambda f, a, b, c, e: a.join(
                e.group_by("id").agg(f.col("amt").sum().alias("total")), on="id"
            ),
            unordered_equal,
        ),
    ],
)


@publisher(
    source=DataGenSrc(data=CASE.data), output_tables=["jm_a", "jm_b", "jm_c", "jm_e"]
)
def jm_pub(
    a: TableFrameSpec, b: TableFrameSpec, c: TableFrameSpec, e: TableFrameSpec
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (a, b, c, e)


@transformer(
    input_tables=[
        f"{SRC}/jm_a@NEW",
        f"{SRC}/jm_b@HEAD",
        f"{SRC}/jm_c@HEAD",
        f"{SRC}/jm_e@HEAD",
    ],
    output_tables=CASE.output_names,
)
def jm_tfr(
    a_versions: TableFramesSpec, b: TableFrameSpec, c: TableFrameSpec, e: TableFrameSpec
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    a = concat(a_versions or [])
    return CASE.transform(a, b, c, e)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def jm_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
