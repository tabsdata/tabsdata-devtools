#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. The rows every sink in this suite writes.

Small and FIXED, which is what makes the write modes legible: re-run the project
and an `append` target grows by three rows while a `replace` target stays at
three. The frame carries a null, a date and a float so format and null handling
have something to act on.
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
                "id": [1, 2, 3],
                "name": ["Ada", "Grace", "Alan"],
                "country": ["GB", "US", None],
                "signup_date": [date(2024, 1, 15), date(2024, 6, 1), date(2025, 2, 28)],
                "revenue": [1250.50, 98000.00, 42.75],
            })),
            Data(pl.DataFrame({
                "order_id": [100, 101, 102, 103],
                "customer_id": [1, 2, 1, 3],
                "amount": [19.99, 250.00, 7.50, 1300.00],
                "status": ["shipped", "shipped", "cancelled", "pending"],
            })),
        ]
    ),
    output_tables=["customers", "orders"],
)
def generate_customers(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
