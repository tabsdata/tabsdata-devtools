#
# Copyright 2026 Tabsdata Inc.
#
"""Expr str casing — ``to_uppercase`` / ``to_lowercase`` / ``to_titlecase`` / ``reverse``."""
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

_INPUT = pl.DataFrame({"s": ["aB", "Cd", "eF gh"]})
CASE = TFCase(
    inputs={"sc_in": _INPUT},
    checks=[
        Check("sc_upper", lambda f, t: t.select(f.col("s").str.to_uppercase().alias("r")), unordered_equal),
        Check("sc_lower", lambda f, t: t.select(f.col("s").str.to_lowercase().alias("r")), unordered_equal),
        Check("sc_title", lambda f, t: t.select(f.col("s").str.to_titlecase().alias("r")), unordered_equal),
        Check("sc_reverse", lambda f, t: t.select(f.col("s").str.reverse().alias("r")), unordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sc_in"])
def sc_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sc_in@NEW"], output_tables=CASE.output_names)
def sc_tfr(
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
def sc_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3])
    return TableFrame.empty()
