#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — SOURCE METADATA on a SQL source: `@td.sql.query` and
`@td.sql.initial_values`.

A SQL source stamps two things:

    `@td.sql.query`            the TEXT of the query that produced the row
    `@td.sql.initial_values`   the BIND VALUES it ran with, JSON-serialised
                               (an empty object `{}` when the query has no binds)

Both are per-QUERY, which is what makes them useful on a multi-query publisher
like this one: the two result sets are separate tables here, but the moment
anything downstream unions them, `@td.sql.query` is the only thing that says
which rows came from which statement.

`@td.sql.initial_values` is the more interesting of the two on an INCREMENTAL
read. A watermark query's text never changes, but the binds do — so the stamp
records the WINDOW each batch covered:

    {"wm": 0}      the first run
    {"wm": 10}     the second
    {"wm": 20}     the third

which turns "why is this row in this batch" into something you can read off the
row, and makes a stalled or rewound cursor visible in the data rather than only
in the function's scratch state. See `postgres_src_incremental` for the cursor
itself.

Every SQL connector in the family stamps the same two columns —
`MySQLSrc`, `MSSQLSrc`, `OracleSrc`, `Db2Src`, `DatabricksSrc` included.
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
    ),
    output_tables=["country_with_metadata", "city_with_metadata"],
)
def read_sql_metadata(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Each table carries the text of ITS OWN query — the two stamps differ.
    return (country, city)
