#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file destination: JSON.

A TEXT format, so everything becomes a string on the way out and a reader has to
be told how to put it back. One thing to know: a tz-AWARE timestamp is written as
ISO-8601 in UTC (`2026-07-14T09:30:15Z`) whatever zone the column declared — the
instant is preserved, only the label is normalised — while a NAIVE timestamp is
written as-is with no offset. PARQUET and AVRO keep the column's own zone.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(paths=["customers.json"], format=DestFileFormat.JSON),
    input_tables=["gen/customers"],
)
def write_json(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
