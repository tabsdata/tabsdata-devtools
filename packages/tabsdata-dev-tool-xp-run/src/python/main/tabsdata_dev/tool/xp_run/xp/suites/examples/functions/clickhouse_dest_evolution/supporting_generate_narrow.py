#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. The NARROW frame (`sku`, `name`) that creates
the target.

It is a SEPARATE publisher from the wide one on purpose: the two writes must be
ORDERED, and two tables published by ONE function land in ONE plan, whose
subscribers run concurrently and in no particular order. Two publishers give the
suite two triggers to order, and its trigger list declares this one
`"detached": false` — a GATE that completes before the wide trigger fires.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[Data(pl.DataFrame({"sku": ["A-1", "B-2"], "name": ["Widget", "Gadget"]}))]
    ),
    output_tables=["products_v1"],
)
def generate_narrow(v1: TableFrameSpec) -> TableFrameSpec:
    return v1
