#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MySQL source: `schema_overrides`, per-query dtype hints.

ONE ENTRY PER QUERY, in the same order, and the lengths must match — `None`
leaves that query's schema fully inferred, a dict overrides only the columns it
names.

Reach for it when the driver infers something you do not want: a zero-padded
code that should stay a string, a wide integer you would rather have as a float,
a numeric whose precision differs by database. It is a READ-side cast, so it
costs nothing downstream and keeps the table's schema stable across connectors.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.common.sql.types import DataType
from tabsdatak.conn.mysql import MySQLSrc


@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT code, name, population FROM country",
            "SELECT id, name FROM city",
        ],
        schema_overrides=[
            {"population": DataType.FLOAT},
            None,
        ],
    ),
    output_tables=["country_typed", "city_untyped"],
)
def read_with_type_hints(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # `country.population` arrives as a float rather than the inferred integer.
    return (country, city)
