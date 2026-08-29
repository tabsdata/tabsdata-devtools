#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 source: ONE QUERY, one table.

THE ONE RULE FOR SQL SOURCES
    `queries` declares one INPUT SLOT per statement, and each slot arrives as a
    SINGLE frame (`TableFrameSpec`) — NOT a list. That is the opposite of a file
    source, where every slot is an array because one path may match many files.
    So a SQL publisher's parameters are plain frames with nothing to fold, and
    the i-th query feeds the i-th parameter and lands in the i-th
    `output_tables` entry.

    Queries must be SELECTs. The connector reads them; it does not run DDL/DML.

DB2 SPECIFICS
    Db2 folds UNQUOTED identifiers to UPPERCASE, exactly as Oracle does, so the
    frames come back with `ID` / `NAME` / `COUNTRY_CODE` and anything naming a
    column by string has to match. Row limiting is `FETCH FIRST n ROWS ONLY`.

    NOTE the frames come back with UPPERCASE column names (`CODE`, `NAME`,
    ...), because the identifiers in these queries are unquoted. Alias them
    (`SELECT code AS "code"`) if downstream code should stay dialect-neutral.

A NOTE ON OUTPUT-TABLE NAMES, since this suite has five publishers in one
collection: a table name is unique per COLLECTION, and `fn register` rejects a
function whose `output_tables` collide with a table another function already
owns. That is why this one is `country_only` rather than `country` — which
`read_many_queries` claims.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(queries=["SELECT * FROM country"]),
    output_tables=["country_only"],
)
def read_one_query(country: TableFrameSpec) -> TableFrameSpec:
    return country
