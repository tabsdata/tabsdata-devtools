#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — ClickHouse destination: `if_table_exists="append"`.

INSERT the rows; the table grows across runs, and is CREATED if missing. Not an
upsert — no key matching, no merge. Re-running publishes the same rows again.

A BULK DESTINATION ADDS A STAGING HOP. These connectors do not INSERT row by
row: they write the frame to a staging area and have the warehouse ingest it,
which is why they load fast and why they have a prerequisite a plain database
does not.

    ClickHouse ingests from an OBJECT STORE: the connection carries a `staging`
    block (bucket + credentials + base path) and the server reads the staged
    parquet itself. This suite stages through S3;
    `clickhouse_bulk_out_gcs.yaml` and `_az.yaml` are the same connector with a
    different staging store.

CLICKHOUSE SPECIFICS
    ClickHouse 24.8 has no time-of-day and no interval type, so a `Time` column
    becomes a `DateTime64` on the sentinel date 1970-01-01 and a `Duration`
    becomes an `Int64` in the source column's own unit. `schema_evolution`
    defaults to `"strict"` here — see the clickhouse_dest_evolution suite.

    ONE TARGET PER SUBSCRIBER. This suite has no two-table sink, unlike the
    other warehouses, because writing a SECOND table from the same subscriber
    fails: `Code: 499 ... The specified key does not exist: while reading key
    <prefix>/out_1.parquet`. The server is pointed at a staged object that is
    not there. Give each target its own subscriber.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.clickhouse import ClickHouseDest


@subscriber(
    destination=ClickHouseDest(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
