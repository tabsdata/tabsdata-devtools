#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str matching — ``contains`` (regex + literal) / ``starts_with`` / ``ends_with`` / ``count_matches`` / ``find``."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"s": ["cat", "category", "dog", "a.b"]})
CASE = TFCase(
    inputs={"sm_in": _INPUT},
    checks=[
        Check("sm_contains", lambda f, t: t.select(f.col("s").str.contains("cat").alias("r")), unordered_equal),
        Check("sm_contains_lit", lambda f, t: t.select(f.col("s").str.contains("a.b", literal=True).alias("r")), unordered_equal),
        Check("sm_starts", lambda f, t: t.select(f.col("s").str.starts_with("cat").alias("r")), unordered_equal),
        Check("sm_ends", lambda f, t: t.select(f.col("s").str.ends_with("g").alias("r")), unordered_equal),
        Check("sm_count", lambda f, t: t.select(f.col("s").str.count_matches("a").alias("r")), unordered_equal),
        Check("sm_find", lambda f, t: t.select(f.col("s").str.find("a").alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sm_in"])
def sm_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sm_in@NEW"], output_tables=CASE.output_names)
def sm_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sm_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
