#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. A frame with a date and two nulls, so the CSV
dialect this suite writes and reads back has something to act on.
"""
from __future__ import annotations

from datetime import date

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "sku": ["A-1", "B-2", "C-3"],
                "released": [date(2024, 1, 15), date(2024, 6, 1), None],
                "price": [9.99, None, 42.0],
            }))
        ]
    ),
    output_tables=["products"],
)
def generate_products(products: TableFrameSpec) -> TableFrameSpec:
    return products
