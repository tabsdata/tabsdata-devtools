#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file destination: CSV with the defaults.

Comma separated, header included, a null written as an EMPTY FIELD — which no
reader can tell from an empty string. That is the default worth knowing about,
and `write_csv_dialect.py` is how you fix it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(paths=["customers.csv"], format=DestFileFormat.CSV),
    input_tables=["gen/customers"],
)
def write_csv(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
