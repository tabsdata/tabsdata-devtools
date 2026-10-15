#
# Copyright 2026 Tabsdata Inc.
#

"""caps_merge_batches — the CDC batches the warehouse merge lanes apply, one dev
``DataGenSrc`` publisher per batch (collection ``caps_input``).

``caps_merge_<batch>`` publishes ``cap_merge_<batch>``: the batch's rows of
``_merge_plan.BATCHES``, in order, as ``cap_id, name, qty, op``. The schema is
spelled out because a load or truncate row is null in every data column -- a
bare ``l`` or ``t`` is nothing else -- and a batch must not leave a column's
type to whatever its first row holds. Each warehouse's
``<system>_merge_<batch>`` subscriber merges it onto the batch's target; the
suite triggers the batches one at a time and checks the target after each
(``scripts/verify_merge.py``). See ``_merge_plan.py`` for what each batch proves.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc

try:
    from ._merge_plan import COLUMNS, MARKER, batch
except ImportError:
    from _merge_plan import COLUMNS, MARKER, batch

_SCHEMA = {
    COLUMNS[0]: pl.Int64,
    COLUMNS[1]: pl.String,
    COLUMNS[2]: pl.Int64,
    MARKER: pl.String,
}


def _frame(name: str) -> pl.DataFrame:
    # A plan row is (op, cap_id, name, qty); the frame carries the marker last.
    return pl.DataFrame(
        [(*row[1:], row[0]) for row in batch(name).rows], schema=_SCHEMA, orient="row"
    )


@publisher(source=DataGenSrc(data=[Data(_frame("b1"))]), output_tables=["cap_merge_b1"])
def caps_merge_b1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b2"))]), output_tables=["cap_merge_b2"])
def caps_merge_b2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b3"))]), output_tables=["cap_merge_b3"])
def caps_merge_b3(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b4"))]), output_tables=["cap_merge_b4"])
def caps_merge_b4(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b5"))]), output_tables=["cap_merge_b5"])
def caps_merge_b5(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b6"))]), output_tables=["cap_merge_b6"])
def caps_merge_b6(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b7"))]), output_tables=["cap_merge_b7"])
def caps_merge_b7(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("b8"))]), output_tables=["cap_merge_b8"])
def caps_merge_b8(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("load1"))]), output_tables=["cap_merge_load1"])
def caps_merge_load1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("load2"))]), output_tables=["cap_merge_load2"])
def caps_merge_load2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("trunc1"))]), output_tables=["cap_merge_trunc1"])
def caps_merge_trunc1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("trunc2"))]), output_tables=["cap_merge_trunc2"])
def caps_merge_trunc2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
