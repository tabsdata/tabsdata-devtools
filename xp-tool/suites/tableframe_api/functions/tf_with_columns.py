#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.with_columns — add a column, replace one, named_exprs, and several
at once."""
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

_INPUT = pl.DataFrame({"a": [3, 1, 2], "b": [10, 20, 30]})
CASE = TFCase(
    inputs={"wc_in": _INPUT},
    checks=[
        Check("wc_add", lambda f, t: t.with_columns((f.col("a") + 1).alias("c")), unordered_equal),
        Check("wc_replace", lambda f, t: t.with_columns((f.col("a") * 0).alias("a")), unordered_equal),
        Check("wc_named", lambda f, t: t.with_columns(c=f.col("a") + f.col("b")), unordered_equal),
        Check(
            "wc_multi",
            lambda f, t: t.with_columns((f.col("a") + 1).alias("x"), (f.col("b") - 1).alias("y")),
            unordered_equal,
        ),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["wc_in"])
def wc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/wc_in@NEW"], output_tables=CASE.output_names)
def wc_tfr(
    t_versions: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def wc_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
