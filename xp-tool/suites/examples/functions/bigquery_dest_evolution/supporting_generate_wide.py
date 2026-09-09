#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. The WIDER frame (`sku`, `name`, `price`,
`category`) appended to the table the narrow one created.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "sku": ["C-3", "D-4"],
                "name": ["Doohickey", "Thingamajig"],
                "price": [9.99, 42.00],
                "category": ["tools", "toys"],
            }))
        ]
    ),
    output_tables=["products_v2"],
)
def generate_wide(v2: TableFrameSpec) -> TableFrameSpec:
    return v2
