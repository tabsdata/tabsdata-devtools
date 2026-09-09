#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file destination: RETURNING None, which writes NOTHING.

Not an empty file — no file. The write is not invoked at all, and any previous
file at that path is left exactly as it was.

That is the contract for "this run had nothing worth emitting", and it composes
with the source side: a publisher that returns `None` publishes no version, so
nothing downstream fires, so a sink like this one is never even reached.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(paths=["customers_skipped.csv"], format=DestFileFormat.CSV),
    input_tables=["gen/customers"],
)
def write_nothing(customers: TableFrameSpec) -> TableFrameSpec:
    return None
