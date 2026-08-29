#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 source: SEVERAL QUERIES, one table each.

Three queries, three slots, three tables — all positional. `transactional`
defaults to `True`, so all three run in ONE session and see ONE consistent
snapshot of the database: the three tables cannot disagree with each other, even
if the data changes mid-read.

That consistency is the reason to put related reads in ONE publisher rather than
three. Split them when they are genuinely independent, so one failing does not
hold up the others.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["country", "city", "country_language"],
)
def read_many_queries(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)
