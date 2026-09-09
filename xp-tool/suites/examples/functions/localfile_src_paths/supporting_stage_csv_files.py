#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. Writes the two CSV files the readers in this
suite read back.

It runs REACTIVELY off the generator's publish — a subscriber needs no trigger of
its own — and the suite makes the generator's trigger a GATE (`"detached": false`),
so both files exist before any reader fires.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(
        paths=["customers_2024.csv", "customers_2025.csv"],
        format=DestFileFormat.CSV,
    ),
    input_tables=["gen/customers_2024", "gen/customers_2025"],
)
def stage_csv_files(
    customers_2024: TableFrameSpec,
    customers_2025: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (customers_2024, customers_2025)
