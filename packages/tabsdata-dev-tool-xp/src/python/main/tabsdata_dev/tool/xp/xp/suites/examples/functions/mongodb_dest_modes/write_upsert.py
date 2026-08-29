#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MongoDB destination: UPSERT, the closest thing to a merge in this set.

`update_existing=True` turns each write into an `UpdateOne(..., upsert=True)` on
the `id_field`, so a document whose id already exists is REPLACED rather than
rejected. That makes the sink idempotent: run it as often as you like and the
collection converges on the input.

No other destination in these examples can do this — the SQL and warehouse ones
offer append or replace and nothing in between. It works here because MongoDB
takes a per-document id.

The other knobs on this write: `docs_per_trx` bounds the batch (and, with
`use_trxs=True` on a replica set, wraps each batch in a MongoDB transaction),
`fail_on_duplicate_key` decides whether a collision raises or is logged, and
`maintain_order` trades speed for deterministic insert order.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_upsert", "id")],
        if_collection_exists="append",
        update_existing=True,
        docs_per_trx=500,
        fail_on_duplicate_key=True,
    ),
    input_tables=["gen/customers"],
)
def write_upsert(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
