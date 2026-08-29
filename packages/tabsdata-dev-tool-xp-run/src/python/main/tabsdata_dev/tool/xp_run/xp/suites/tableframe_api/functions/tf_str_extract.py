#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str extraction — ``extract`` (regex group), ``contains_any`` (multi-pattern), ``replace_many`` (mapping)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"s": ["id=12", "id=34", "id=56"]})
CASE = TFCase(
    inputs={"sx_in": _INPUT},
    checks=[
        Check("sx_extract", lambda f, t: t.select(f.col("s").str.extract(r"id=(\d+)", 1).alias("r")), unordered_equal),
        Check("sx_contains_any", lambda f, t: t.select(f.col("s").str.contains_any(["12", "34"]).alias("r")), unordered_equal),
        Check("sx_replace_many", lambda f, t: t.select(f.col("s").str.replace_many({"id": "ID"}).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sx_in"])
def sx_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sx_in@NEW"], output_tables=CASE.output_names)
def sx_tfr(t: TableFrameSpec) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sx_sub(c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec) -> TableFrameSpec:
    CASE.verify([c0, c1, c2])
    return TableFrame.empty()
