#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks source: A COMPOSITE CURSOR.

`max_for` takes SEVERAL columns and ranks by them in order — the first is
primary, each next one breaks ties on the previous — and returns them all from
the winning row. That is what a `(timestamp, id)` cursor needs: paging a table
whose timestamps are not unique requires both halves, and one call gets them.

A NOTE ON TIMESTAMP CURSORS: a seed, and anything `ctx.set_attr` stores, must be
a BASIC value (str / int / float / bool). So a datetime cursor travels as an
ISO-8601 STRING and the database casts it back:

    queries=["SELECT * FROM orders WHERE updated_at > CAST(:since AS timestamp) "
             "ORDER BY updated_at, id LIMIT 10"],
    initial_values={"since": "2024-01-01T00:00:00+00:00"},
    ...
    top = orders.max_for("updated_at", "id")
    ctx.set_attr("since", top["updated_at"].isoformat())

The world sample has no timestamp column, so the live version below ranks by id
and reports population alongside it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TransactionCtx, publisher
from tabsdatak.conn.databricks import DatabricksSrc


@publisher(
    source=DatabricksSrc(
        queries=[
            "SELECT id, name, country_code, population FROM city "
            "WHERE id > :since ORDER BY id LIMIT 10"
        ],
        initial_values={"since": 0},
    ),
    output_tables=["city_since"],
)
def read_composite_watermark(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("id", "population")
    if top is not None and top["id"] is not None:
        ctx.set_attr("since", int(top["id"]))
    return city
