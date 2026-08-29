#
# Copyright 2026 Tabsdata Inc.
#
"""Expr comparison methods — ``eq ne lt le gt ge eq_missing ne_missing``."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1, 2, 3], "b": [2, 2, 2]})
CASE = TFCase(
    inputs={"eqm_in": _INPUT},
    checks=[
        Check("eqm_eq", lambda f, t: t.select(f.col("a").eq(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_ne", lambda f, t: t.select(f.col("a").ne(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_lt", lambda f, t: t.select(f.col("a").lt(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_le", lambda f, t: t.select(f.col("a").le(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_gt", lambda f, t: t.select(f.col("a").gt(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_ge", lambda f, t: t.select(f.col("a").ge(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_eqm", lambda f, t: t.select(f.col("a").eq_missing(f.col("b")).alias("r")), unordered_equal),
        Check("eqm_nem", lambda f, t: t.select(f.col("a").ne_missing(f.col("b")).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["eqm_in"])
def eqm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/eqm_in@NEW"], output_tables=CASE.output_names)
def eqm_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def eqm_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
    c6: TableFrameSpec,
    c7: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5, c6, c7])
    return TableFrame.empty()
