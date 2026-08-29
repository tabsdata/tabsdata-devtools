#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 destination: CSV with `format_cfg`, for a consumer that
demands a particular dialect.

`format_cfg` is keyed by the `DestFileFormat` and only CSV takes options. It is
SIDE-TYPED: these are WRITER keys, and a READER key (`has_header`,
`try_parse_dates`, ...) here fails validation at decoration time — the two sides
are separate vocabularies.

Writer keys: `separator`, `quote_char`, `eol_char`, `include_header`,
`null_value`, `quote_style`, `date_format`, `time_format`, `datetime_format`,
`float_precision`, `float_scientific`, `maintain_order`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.s3 import S3Dest


@subscriber(
    destination=S3Dest(
        paths=["customers_dialect.csv"],
        format=DestFileFormat.CSV,
        format_cfg={
            DestFileFormat.CSV: {
                "separator": ";",
                "include_header": True,
                # An explicit null TOKEN, so "missing" stays distinguishable
                # from "empty string" — the most useful writer option there is.
                "null_value": "NULL",
                # Pin the rendering instead of taking the defaults.
                "date_format": "%d/%m/%Y",
                "float_precision": 2,
                # "necessary" (the default) quotes only what needs it; the
                # alternatives are "always", "non_numeric" and "never".
                "quote_style": "necessary",
            }
        },
    ),
    input_tables=["gen/customers"],
)
def write_csv_dialect(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
