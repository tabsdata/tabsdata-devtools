#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Databricks destination: `if_table_exists="append"`.

INSERT the rows; the table grows across runs, and is CREATED if missing. Not an
upsert — no key matching, no merge. Re-running publishes the same rows again.

A BULK DESTINATION ADDS A STAGING HOP. These connectors do not INSERT row by
row: they write the frame to a staging area and have the warehouse ingest it,
which is why they load fast and why they have a prerequisite a plain database
does not.

    Databricks ingests through a VOLUME: the frame is written there and `COPY
    INTO` loads it. The connection's `volume` MUST already exist — a missing
    volume is the single most common first-run failure on this connector.

DATABRICKS SPECIFICS
    Target names are completed from the connection's `catalog` / `schema`, so
    `customers_append` is really `<catalog>.<schema>.customers_append`.
    Databricks also has `schema_evolution` (default `"update"`) — see the
    databricks_dest_evolution suite.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(tables=["customers_append"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
