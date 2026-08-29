#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks source: `transactional=False`.

Each query gets its OWN connection and autocommits independently, instead of
sharing one transactional session. Cheaper and friendlier to a busy server —
and the queries can see different states of the database, which is precisely
what the default protects you from.

Use it when the reads have no consistency requirement between them, as here.
Keep the default when they do.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.databricks import DatabricksSrc


@publisher(
    source=DatabricksSrc(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        transactional=False,
    ),
    output_tables=["country_slim", "city_slim"],
)
def read_without_transaction(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)
