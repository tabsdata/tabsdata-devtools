#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — the same SQL read with metadata dropped.

`src_cfg={"tabsdata.src_metadata.drop": True}` works identically on every source
kind — the key is shared, not per-connector — so this is the SQL twin of
`read_file_metadata_dropped.py`.

THE CASE FOR DROPPING IT IS STRONGEST HERE. `@td.sql.query` embeds the statement
text in EVERY ROW: on a wide table that is a real width cost, and on a table
other teams read it publishes your schema's internals and any literal you
happened to inline. A query with a customer id or an internal hostname in a
`WHERE` clause ends up stamped on every row it returned.

The counter-argument is the same as everywhere: you lose it exactly when you need
it. A reasonable middle path is to keep the metadata at ingest and drop it at the
boundary — a transformer that `select`s only the data columns, or a subscriber
that projects before writing — so the provenance exists inside your pipeline and
not outside it.

Same two queries as `read_sql_metadata.py`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.postgres import PostgresSrc


@publisher(
    source=PostgresSrc(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        src_cfg={"tabsdata.src_metadata.drop": True},
    ),
    output_tables=["country_without_metadata", "city_without_metadata"],
)
def read_sql_metadata_dropped(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)
