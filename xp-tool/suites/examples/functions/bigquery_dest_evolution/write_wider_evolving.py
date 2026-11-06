#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery: APPEND a WIDER frame, with evolution ALLOWED.

`schema_evolution="update"`
has the connector ALTER the target before the load (the default `iceberg`
engine), adding the columns as NULLABLE
so `price` and `category` are ADDED to the table, and the two rows written before
them read back NULL there.

THE SAME TWO VALUES ON EVERY TABLE DESTINATION — Databricks, BigQuery,
Snowflake, ClickHouse, StarRocks, PostgreSQL, MySQL, SQL Server, Oracle, Db2:

    "strict"  (DEFAULT)  refuses a batch with a column the table lacks or a
                         wider type
    "update"             adds the column and widens the type, and refuses a
                         change the database cannot make

    A column the BATCH lacks is written NULL either way. BigQuery and Snowflake
    also take `dest_cfg={"<system>.schema_evolution_engine": ...}`: `"iceberg"`
    (the default) has the connector ALTER the table itself, `"native"` leaves
    `"update"` to the warehouse's own load options, which add a column but never
    widen one.

    On BigQuery the permissive value is `"update"` and the DEFAULT is
    `"strict"`. Every subscriber in this suite spells the value out rather than
    relying on that default.

EVOLUTION ONLY GROWS A TABLE. A REMOVED column, a RENAMED one or a type that
narrows is not schema evolution — it is a migration, and no setting here will
do it for you.
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
