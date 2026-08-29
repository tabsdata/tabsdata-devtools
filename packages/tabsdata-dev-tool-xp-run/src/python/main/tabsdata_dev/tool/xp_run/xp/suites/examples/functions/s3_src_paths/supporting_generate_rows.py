#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. Emits the three fixed frames this suite stages
as files, so the readers have something to read.

`DataGenSrc` carries its dataframes inline (base64 parquet on the wire) and is
backed by no external system, so a suite that needs input data costs one extra
no-op `dev` domain rather than a second real backend. It is SINGLE mode: one
frame per `Data`, so these parameters are plain frames, not lists.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            # Two same-shaped customer frames, so a wildcard has something to
            # union, and one differently-shaped orders frame, so a multi-path
            # read has two genuinely different tables.
            Data(pl.DataFrame({
                "id": [1, 2, 3],
                "name": ["Ada", "Grace", "Alan"],
                "country": ["GB", "US", "GB"],
            })),
            Data(pl.DataFrame({
                "id": [4, 5],
                "name": ["Edsger", "Barbara"],
                "country": ["NL", "US"],
            })),
            Data(pl.DataFrame({
                "order_id": [100, 101, 102],
                "customer_id": [1, 2, 4],
                "amount": [19.99, 250.00, 7.50],
            })),
        ]
    ),
    output_tables=["customers_2024", "customers_2025", "orders"],
)
def generate_rows(
    customers_2024: TableFrameSpec,
    customers_2025: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (customers_2024, customers_2025, orders)
