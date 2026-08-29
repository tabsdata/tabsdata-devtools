#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 source: ONE FIXED PATH.

`paths` declares one INPUT SLOT per entry, and every slot arrives as a LIST of
frames (`TableFramesSpec`) — one frame per file that entry matched. That holds
even for a path with no wildcard: this slot is a list of exactly one frame.

So a file publisher's parameter is ALWAYS a list, and the body always folds it.
`concat` of a one-element list is that element; writing it this way means the
body does not change if the path later grows a wildcard.

The connection (`connections/s3_file_in.yaml` / `s3_file_out.yaml`)
    carries the bucket, the region, the AWS credentials and the `base_path`
    prefix. None of that is in this file — which is what lets the same
    function be pointed at another bucket, or at GCS, without a rewrite.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.s3 import S3Src
from tabsdatak.tableframe.functions import concat


@publisher(
    source=S3Src(paths=["customers_2024.csv"]),
    output_tables=["customers_2024"],
)
def read_fixed_path(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
