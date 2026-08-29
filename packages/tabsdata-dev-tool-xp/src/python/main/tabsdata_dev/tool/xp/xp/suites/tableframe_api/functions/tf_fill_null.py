#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame.fill_null — literal value, min/max strategies, and forward/backward
(sorted first so the directional fills are deterministic)."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal
except ImportError:
    from _harness import OPS, SRC, Check, TFCase, ordered_equal, unordered_equal

_INPUT = pl.DataFrame({"id": [1, 2, 3, 4], "v": [10, None, None, 40]})
CASE = TFCase(
    inputs={"fn_in": _INPUT},
    checks=[
        Check("fn_value", lambda f, t: t.fill_null(0), unordered_equal),
        Check("fn_min", lambda f, t: t.fill_null(strategy="min"), unordered_equal),
        Check("fn_max", lambda f, t: t.fill_null(strategy="max"), unordered_equal),
        Check("fn_forward", lambda f, t: t.sort("id").fill_null(strategy="forward"), ordered_equal),
        Check("fn_backward", lambda f, t: t.sort("id").fill_null(strategy="backward"), ordered_equal),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["fn_in"])
def fn_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/fn_in@NEW"], output_tables=CASE.output_names)
def fn_tfr(
    t: TableFrameSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return CASE.transform(t)


@subscriber(destination=TrashDest(), input_tables=[f"{OPS}/{n}" for n in CASE.output_names])
def fn_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4])
    return TableFrame.empty()
