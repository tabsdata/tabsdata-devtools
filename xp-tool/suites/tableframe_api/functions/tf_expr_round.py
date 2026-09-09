#
# Copyright 2026 Tabsdata Inc.
#
"""Expr rounding — floor/ceil/round (digits + mode)/round_sig_figs."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, unordered_equal

_INPUT = pl.DataFrame({"a": [1.4, 2.5, -1.6, 3.14159]})
CASE = TFCase(
    inputs={"rd_in": _INPUT},
    checks=[
        Check("rd_floor", lambda f, t: t.select(f.col("a").floor().alias("r")), unordered_equal),
        Check("rd_ceil", lambda f, t: t.select(f.col("a").ceil().alias("r")), unordered_equal),
        Check("rd_round0", lambda f, t: t.select(f.col("a").round(0).alias("r")), unordered_equal),
        Check("rd_round2", lambda f, t: t.select(f.col("a").round(2).alias("r")), unordered_equal),
        Check("rd_round_mode", lambda f, t: t.select(f.col("a").round(0, mode="half_away_from_zero").alias("r")), unordered_equal),
        Check("rd_sigfigs", lambda f, t: t.select(f.col("a").round_sig_figs(2).alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["rd_in"])
def rd_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/rd_in@NEW"], output_tables=CASE.output_names)
def rd_tfr(
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
def rd_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
