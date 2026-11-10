#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str replacement — ``replace`` (first match) and ``replace_all``, each in regex and literal form."""
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

_INPUT = pl.DataFrame({"s": ["aXaXa", "bYb", "cZc"]})
CASE = TFCase(
    inputs={"sr_in": _INPUT},
    checks=[
        Check("sr_replace", lambda f, t: t.select(f.col("s").str.replace("a", "_").alias("r")), unordered_equal),
        Check("sr_replace_lit", lambda f, t: t.select(f.col("s").str.replace("a", "_", literal=True).alias("r")), unordered_equal),
        Check("sr_replace_all", lambda f, t: t.select(f.col("s").str.replace_all("a", "_").alias("r")), unordered_equal),
        Check("sr_replace_all_lit", lambda f, t: t.select(f.col("s").str.replace_all("X", "_", literal=True).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sr_in"])
def sr_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sr_in@NEW"], output_tables=CASE.output_names)
def sr_tfr(
    t_versions: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    t = concat(t_versions or [])
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def sr_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
