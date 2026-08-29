#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mongodb — MongoDB dest write modes. Schemaless, so modes differ from SQL:
``if_collection_exists`` (append/replace) + upsert via ``collections_with_ids``
(id_source_column) and ``update_existing``. Input from dev datagen ``caps_input/cap_rows``
(``code`` is the natural key).

- ``mongodb_out_append``  : append into ``cap_append`` (auto ``_id``) — grows on re-run.
- ``mongodb_out_replace`` : ``if_collection_exists="replace"`` -> drops ``cap_replace`` each run.
- ``mongodb_out_upsert``  : ``id`` = ``code`` + ``update_existing=True`` -> re-runs UPSERT the
                            same 3 docs (count stays 3), not duplicate.
- ``mongodb_out_none``    : return-None contract.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.mongodb import MongoDBDest


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("cap_append", None)],
        if_collection_exists="append",
    ),
    input_tables=["caps_input/cap_rows"],
)
def mongodb_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("cap_replace", None)],
        if_collection_exists="replace",
    ),
    input_tables=["caps_input/cap_rows"],
)
def mongodb_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MongoDBDest(
        # `code` becomes _id; update_existing -> re-runs upsert the same docs.
        collections_with_ids=[("cap_upsert", "code")],
        if_collection_exists="append",
        update_existing=True,
    ),
    input_tables=["caps_input/cap_rows"],
)
def mongodb_out_upsert(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MongoDBDest(
        collections_with_ids=[("cap_append", None)],
        if_collection_exists="append",
    ),
    input_tables=["caps_input/cap_rows"],
)
def mongodb_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None
