#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — SQL Server source: WHEN THE QUERY MATCHES NOTHING.

Zero rows means the slot arrives as `None`, and returning `None` publishes NO new
version of the table. Downstream `@NEW` dependants do not fire — which is what
"nothing arrived this run" should mean.

Returning an EMPTY FRAME instead publishes a real, empty version and DOES trigger
downstream work. Both are legitimate; pick deliberately.

The body is written the long way to make the contract visible. In real code
`return city` does the same thing, because the slot is already `None`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.mssql import MSSQLSrc


@publisher(
    source=MSSQLSrc(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["city_empty"],
)
def read_no_rows(city: TableFrameSpec) -> TableFrameSpec:
    if city is None:
        return None
    return city
