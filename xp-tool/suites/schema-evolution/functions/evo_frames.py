#
# Copyright 2026 Tabsdata Inc.
#

"""evo_frames — the frames the schema-evolution lanes write, one dev ``DataGenSrc``
publisher each (collection ``evo_input``).

``<publisher>`` publishes the table of the same name: ``_evo_plan.FRAMES``' frame,
its schema spelled out -- a 32-bit ``score`` is what makes ``evo_narrow``
narrow, and a merge batch's marker column is a plain string. Every lane
registers all of them; the suite triggers them a phase at a time (see
``_evo_plan.py``), and each fires the subscribers of the cases it feeds.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc

try:
    from ._evo_plan import FRAMES
except ImportError:
    from _evo_plan import FRAMES


def _frame(name: str) -> pl.DataFrame:
    columns, rows = FRAMES[name]
    schema = {column: getattr(pl, kind) for column, kind in columns}
    return pl.DataFrame(list(rows), schema=schema, orient="row")


@publisher(source=DataGenSrc(data=[Data(_frame("evo_base"))]), output_tables=["evo_base"])
def evo_base(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("evo_narrow"))]), output_tables=["evo_narrow"])
def evo_narrow(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_merge_first"))]),
    output_tables=["evo_merge_first"],
)
def evo_merge_first(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("evo_added"))]), output_tables=["evo_added"])
def evo_added(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_added_refused"))]),
    output_tables=["evo_added_refused"],
)
def evo_added_refused(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("evo_lacking"))]), output_tables=["evo_lacking"])
def evo_lacking(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("evo_wide"))]), output_tables=["evo_wide"])
def evo_wide(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_wide_strict"))]),
    output_tables=["evo_wide_strict"],
)
def evo_wide_strict(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(source=DataGenSrc(data=[Data(_frame("evo_fitting"))]), output_tables=["evo_fitting"])
def evo_fitting(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_merge_lacking"))]),
    output_tables=["evo_merge_lacking"],
)
def evo_merge_lacking(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_merge_added"))]),
    output_tables=["evo_merge_added"],
)
def evo_merge_added(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_frame("evo_merge_added_refused"))]),
    output_tables=["evo_merge_added_refused"],
)
def evo_merge_added_refused(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
