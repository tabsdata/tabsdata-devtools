#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — GCS source: CONFIGURING THE CSV DIALECT with `format_cfg`.

`format_cfg` is keyed by the `SrcFileFormat` — `{SrcFileFormat.CSV: {...}}` —
and only CSV takes options; every other format maps to `{}` or is omitted.

The dict below is the mirror image of the one `supporting_stage_dialect_csv.py`
wrote with. GET ANY OF IT WRONG AND THE READ STILL SUCCEEDS: a wrong separator
gives one wide string column, a missing `null_values` gives the literal text
`"NULL"`, no `try_parse_dates` gives a string where a date belongs. A CSV dialect
mismatch is a silent-wrong-data bug, not an error — which is the reason to pin
the dialect on both sides rather than hope.

Reader keys, all optional: `separator`, `quote_char`, `eol_char`, `encoding`,
`null_values`, `missing_is_null`, `truncate_ragged_lines`, `comment_prefix`,
`try_parse_dates`, `decimal_comma`, `has_header`, `skip_rows`,
`skip_rows_after_header`, `raise_if_empty`, `ignore_errors`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.gcs import GCSSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=GCSSrc(
        paths=["products.csv"],
        format=SrcFileFormat.CSV,
        format_cfg={
            SrcFileFormat.CSV: {
                "separator": ";",
                "has_header": True,
                "null_values": ["NULL"],
                "try_parse_dates": True,
                # Other reader keys worth knowing, left at their defaults here:
                #   "skip_rows": 2            skip N lines before the header
                #   "comment_prefix": "#"     drop lines starting with it
                #   "encoding": "utf8-lossy"  survive undecodable bytes
                #   "decimal_comma": True     European decimals (1,5 -> 1.5)
                #   "ignore_errors": True     null a bad field instead of failing
            }
        },
    ),
    output_tables=["products_roundtrip"],
)
def read_csv_dialect(products: TableFramesSpec) -> TableFrameSpec:
    # Round-trips to the frame the generator emitted: `released` is a date again
    # and the two missing values are nulls again, not the string "NULL".
    return concat(products)
