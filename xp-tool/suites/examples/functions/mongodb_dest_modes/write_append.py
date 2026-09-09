#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MongoDB destination: APPEND with an explicit id field.

MONGODB DOES NOT USE `tables` / `if_table_exists`. It writes documents, so:

    `collections_with_ids`   a list of `(collection, id_field)` PAIRS, one write
                             slot per entry. `collection` may be qualified
                             `<database>.<collection>`; a bare name uses the
                             database in the connection URI. `id_field` is the
                             document field used as the unique id — pass `None`
                             to let MongoDB generate `_id` itself.
    `if_collection_exists`   `"append"` (default) leaves existing documents in
                             place; `"replace"` DROPS the collection first.

    Everything else about the destination shape is the same: one slot per entry,
    fed positionally by `input_tables`, and a returned `None` writes nothing.

    BSON HAS NO TYPE for three of the values a table can carry, so the write
    converts them: a `Date` becomes a BSON datetime at midnight UTC, a `Time`
    becomes one on the sentinel date 1970-01-01 UTC, and a `Duration` becomes an
    integer count of nanoseconds. `Decimal` maps to `Decimal128` and round-trips
    exactly.

`("customers_append", "id")` names `id` as the document id, so re-running this
tries to insert documents whose ids already exist — and with the default
`update_existing=False` that is an `InsertOne` collision, which aborts the batch.
`write_upsert.py` is the mode that wants to be re-run.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("customers_append", "id")],
        if_collection_exists="append",
    ),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
