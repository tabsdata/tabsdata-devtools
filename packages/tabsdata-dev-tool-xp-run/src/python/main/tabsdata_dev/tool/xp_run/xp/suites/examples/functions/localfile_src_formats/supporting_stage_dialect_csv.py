#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example, but half of the point: it writes the awkward
CSV that `read_csv_dialect` reads back, so the two `format_cfg` dicts can be
compared side by side.

`format_cfg` is SIDE-TYPED: these are WRITER keys, and passing one of them to a
source (or a reader key to a destination) fails validation at decoration time,
before anything runs.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(
        paths=["products.csv"],
        format=DestFileFormat.CSV,
        format_cfg={
            DestFileFormat.CSV: {
                "separator": ";",
                "include_header": True,
                # The token this file uses for a missing value. Without it a null
                # is written as an empty field, which no reader can tell from an
                # empty string.
                "null_value": "NULL",
                "date_format": "%Y-%m-%d",
            }
        },
    ),
    input_tables=["gen/products"],
)
def stage_dialect_csv(products: TableFrameSpec) -> TableFrameSpec:
    return products
