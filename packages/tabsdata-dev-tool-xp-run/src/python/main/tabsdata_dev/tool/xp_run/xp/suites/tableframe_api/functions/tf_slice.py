#
# Copyright 2026 Tabsdata Inc.
#
"""TableFrame row slicing — head, tail, limit, slice, first, last.

Order-sensitive, so each op sorts on the unique ``id`` first and verifies with
ordered_equal."""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.dev import DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame

try:
    from ._harness import IGNORE, OPS, SRC, Check, TFCase, ordered_equal
except ImportError:
    from _harness import IGNORE, OPS, SRC, Check, TFCase, ordered_equal

_INPUT = pl.DataFrame({"id": [3, 1, 2, 4, 5], "v": [30, 10, 20, 40, 50]})
CASE = TFCase(
    inputs={"sl_in": _INPUT},
    checks=[
        Check("sl_head", lambda f, t: t.sort("id").head(2), ordered_equal),
        Check("sl_tail", lambda f, t: t.sort("id").tail(2), ordered_equal),
        Check("sl_limit", lambda f, t: t.sort("id").limit(3), ordered_equal),
        Check("sl_slice", lambda f, t: t.sort("id").slice(1, 2), ordered_equal),
        # TableFrame exposes .first()/.last() as frame methods, but polars
        # DataFrame has neither, so the op cannot be re-run on the polars surface
        # to compare — a genuine API divergence. Run on the TableFrame path only.
        Check("sl_first", lambda f, t: t.sort("id").first(), IGNORE),
        Check("sl_last", lambda f, t: t.sort("id").last(), IGNORE),
    ],
)


@publisher(source=DataGenSrc(data=CASE.data), output_tables=["sl_in"])
def sl_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t


@transformer(input_tables=[f"{SRC}/sl_in@NEW"], output_tables=CASE.output_names)
def sl_tfr(
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
def sl_sub(
    c0: TableFrameSpec,
    c1: TableFrameSpec,
    c2: TableFrameSpec,
    c3: TableFrameSpec,
    c4: TableFrameSpec,
    c5: TableFrameSpec,
) -> TableFrameSpec:
    CASE.verify([c0, c1, c2, c3, c4, c5])
    return TableFrame.empty()
