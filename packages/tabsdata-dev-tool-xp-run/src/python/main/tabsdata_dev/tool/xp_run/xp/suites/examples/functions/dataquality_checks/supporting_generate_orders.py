#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. Eight raw orders of KNOWN composition.

Five are clean; three have exactly one problem each — a null amount (row 6), a
status outside the allowed set (row 7), and a malformed email plus a three-letter
country (row 8). Knowing the composition is what makes the summary tallies and
the quarantine tables readable rather than plausible.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "order_id": [1, 2, 3, 4, 5, 6, 7, 8],
                "customer_email": [
                    "ada@example.com",
                    "grace@example.com",
                    "alan@example.com",
                    "edsger@example.com",
                    "barbara@example.com",
                    "linus@example.com",
                    "ken@example.com",
                    "not-an-email",
                ],
                "amount": [19.99, 250.00, 7.50, 1300.00, 42.00, None, 88.00, 15.00],
                "status": [
                    "pending", "shipped", "cancelled", "shipped",
                    "pending", "shipped", "REFUNDED", "pending",
                ],
                "country": ["GB", "US", "GB", "NL", "US", "DE", "FR", "ESP"],
            }))
        ]
    ),
    output_tables=["raw_orders"],
)
def generate_orders(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
