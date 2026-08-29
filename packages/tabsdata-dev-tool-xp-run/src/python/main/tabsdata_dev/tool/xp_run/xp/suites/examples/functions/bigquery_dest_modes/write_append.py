#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — BigQuery destination: `if_table_exists="append"`.

INSERT the rows; the table grows across runs, and is CREATED if missing. Not an
upsert — no key matching, no merge. Re-running publishes the same rows again.

A BULK DESTINATION ADDS A STAGING HOP. These connectors do not INSERT row by
row: they write the frame to a staging area and have the warehouse ingest it,
which is why they load fast and why they have a prerequisite a plain database
does not.

    BigQuery ingests from a GCS bucket named on the connection, which also
    carries the service-account key, the project and the dataset.

BIGQUERY SPECIFICS
    NOTE THE BACKTICKS. BigQuery wraps the WHOLE name in ONE backtick pair —
    `my-project.dataset.table` — rather than quoting each part, which is what
    lets a project id containing hyphens round-trip. Every other connector here
    quotes per part, or not at all. Partial names are completed from the
    connection's `project` / `dataset`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


@subscriber(
    destination=BigQueryDest(tables=["`customers_append`"], if_table_exists="append"),
    input_tables=["gen/customers"],
)
def write_append(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
