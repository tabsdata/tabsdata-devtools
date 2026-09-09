#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MongoDB destination: TWO COLLECTIONS from one subscriber.

Two pairs, two input tables, two returned frames — positional, like every other
destination. Note the id fields differ per entry: `customers` is keyed by `id`
and `orders` by `order_id`, which is the reason the pair carries the id field
rather than the destination carrying one for all of them.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_both", "id"), ("orders_both", "order_id")],
        if_collection_exists="replace",
    ),
    input_tables=["gen/customers", "gen/orders"],
)
def write_two_collections(
    customers: TableFrameSpec,
    orders: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers, orders)
