#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MongoDB destination: REPLACE, which DROPS the collection first.

Not a truncate — a drop. Indexes and collection options defined on the target go
with it, which is the difference worth knowing about before pointing `replace` at
a collection someone tuned by hand.

`id_field=None` here lets MongoDB generate `_id`, so nothing can collide and the
collection holds exactly this run's documents.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_replace", None)],
        if_collection_exists="replace",
    ),
    input_tables=["gen/customers"],
)
def write_replace(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
