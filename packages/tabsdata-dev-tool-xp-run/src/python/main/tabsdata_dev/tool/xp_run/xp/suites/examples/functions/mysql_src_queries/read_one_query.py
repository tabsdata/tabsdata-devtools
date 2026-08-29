#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MySQL source: ONE QUERY, one table.

THE ONE RULE FOR SQL SOURCES
    `queries` declares one INPUT SLOT per statement, and each slot arrives as a
    SINGLE frame (`TableFrameSpec`) — NOT a list. That is the opposite of a file
    source, where every slot is an array because one path may match many files.
    So a SQL publisher's parameters are plain frames with nothing to fold, and
    the i-th query feeds the i-th parameter and lands in the i-th
    `output_tables` entry.

    Queries must be SELECTs. The connector reads them; it does not run DDL/DML.

MYSQL SPECIFICS
    MySQL takes the same `LIMIT n` as PostgreSQL and preserves identifier case,
    so these queries are byte-identical to the PostgreSQL ones.

A NOTE ON OUTPUT-TABLE NAMES, since this suite has five publishers in one
collection: a table name is unique per COLLECTION, and `fn register` rejects a
function whose `output_tables` collide with a table another function already
owns. That is why this one is `country_only` rather than `country` — which
`read_many_queries` claims.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.mysql import MySQLSrc


@publisher(
    source=MySQLSrc(queries=["SELECT * FROM country"]),
    output_tables=["country_only"],
)
def read_one_query(country: TableFrameSpec) -> TableFrameSpec:
    return country
