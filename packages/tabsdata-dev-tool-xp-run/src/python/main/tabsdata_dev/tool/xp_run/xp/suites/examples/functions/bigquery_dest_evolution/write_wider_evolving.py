#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery: APPEND a WIDER frame, with evolution ALLOWED.

`schema_evolution="update"`
sets the load job's schema-update options, adding the columns as NULLABLE
so `price` and `category` are ADDED to the table, and the two rows written before
them read back NULL there.

THE VALUES AND THE DEFAULTS DIFFER PER CONNECTOR, which is the thing to carry
away — identical code is permissive on one warehouse and strict on another:

    Databricks   "update"  (DEFAULT) | "strict"
    BigQuery     "update"  (DEFAULT) | "strict"
    ClickHouse   "strict"  (DEFAULT) | "iceberg"
    StarRocks    "strict"  (DEFAULT) | "iceberg"   — but its INSERT ... SELECT
                 FROM FILES load path does not pre-ALTER the target, so a widened
                 frame fails on column count rather than evolving. The field
                 exists; the path cannot use it yet.
    Snowflake, PostgreSQL, MySQL, SQL Server, Oracle, Db2, MongoDB, Druid
                 no `schema_evolution` field at all — append and replace are the
                 whole vocabulary, and a mismatched frame fails.

    On BigQuery the permissive value is `"update"` and the DEFAULT is
    `"update"`. Every subscriber in this suite spells the value out rather than
    relying on that default.

EVOLUTION IS ADDITIVE ONLY, everywhere. A REMOVED column, a RENAMED one or a
changed TYPE is not schema evolution — it is a migration, and no setting here
will do it for you.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


@subscriber(
    destination=BigQueryDest(
        tables=["`products_evolve`"],
        if_table_exists="append",
        schema_evolution="update",
    ),
    input_tables=["gen/products_v2"],
)
def write_wider_evolving(v2: TableFrameSpec) -> TableFrameSpec:
    return v2
