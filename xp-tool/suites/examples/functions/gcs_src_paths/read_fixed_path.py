#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — GCS source: ONE FIXED PATH.

`paths` declares one INPUT SLOT per entry, and every slot arrives as a LIST of
frames (`TableFramesSpec`) — one frame per file that entry matched. That holds
even for a path with no wildcard: this slot is a list of exactly one frame.

So a file publisher's parameter is ALWAYS a list, and the body always folds it.
`concat` of a one-element list is that element; writing it this way means the
body does not change if the path later grows a wildcard.

The connection (`connections/gcs_file_in.yaml` / `gcs_file_out.yaml`)
    carries the bucket, a service-account key and the `base_path` prefix.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.gcs import GCSSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=GCSSrc(paths=["customers_2024.csv"]),
    output_tables=["customers_2024"],
)
def read_fixed_path(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
