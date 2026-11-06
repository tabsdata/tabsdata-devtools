#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Snowflake destination: `if_table_exists="append"`.

INSERT the rows; the table grows across runs, and is CREATED if missing. Not an
upsert — no key matching, no merge. Re-running publishes the same rows again.

A BULK DESTINATION ADDS A STAGING HOP. These connectors do not INSERT row by
row: they write the frame to a staging area and have the warehouse ingest it,
which is why they load fast and why they have a prerequisite a plain database
does not.

    Snowflake ingests through a STAGE: the frame is written there and `PUT` +
    `COPY INTO` load it. The connection's `stage` is optional — when unset the
    plugin creates a session-scoped TEMPORARY stage, so there is nothing to
    provision.

SNOWFLAKE SPECIFICS
    Snowflake folds unquoted identifiers to UPPERCASE, so `customers_append`
    below creates `CUSTOMERS_APPEND`. Double-quote the name in `tables` to keep
    it lowercase. `schema_evolution` defaults to `"strict"` here, as on every
    table destination; `"update"` adds a column and widens a type.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
