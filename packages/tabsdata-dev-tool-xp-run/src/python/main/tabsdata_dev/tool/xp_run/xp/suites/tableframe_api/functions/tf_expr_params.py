#
# Copyright 2026 Tabsdata Inc.
#
"""Expr deeper param combos — diff(null_behavior), fill_null(strategy), hash(seed), round_sig_figs."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal

_INPUT = pl.DataFrame(
    {
        "id": [1, 2, 3, 4, 5],
        "v": [10, 10, 30, 20, None],
        "x": [1.234, 5.678, -2.5, 3.14159, 0.0],
    }
)
CASE = TFCase(
    inputs={"ep_in": _INPUT},
    checks=[
        Check("ep_diff_drop", lambda f, t: t.sort("id").select(f.col("v").diff(1, null_behavior="drop").alias("r")), ordered_equal),
        Check("ep_fill_max", lambda f, t: t.select(f.col("v").fill_null(strategy="max").alias("r")), unordered_equal),
        Check("ep_hash_seed", lambda f, t: t.select(f.col("v").hash(seed=42).alias("r")), unordered_equal),
        Check("ep_round_sig3", lambda f, t: t.select(f.col("x").round_sig_figs(3).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["ep_in"])
def ep_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/ep_in@NEW"], output_tables=CASE.output_names)
def ep_tfr(
    t: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def ep_sub(
    c0: TableFrameSpec, c1: TableFrameSpec, c2: TableFrameSpec, c3: TableFrameSpec
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
