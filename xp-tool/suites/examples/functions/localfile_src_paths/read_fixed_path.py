#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file source: ONE FIXED PATH.

`paths` declares one INPUT SLOT per entry, and every slot arrives as a LIST of
frames (`TableFramesSpec`) — one frame per file that entry matched. That holds
even for a path with no wildcard: this slot is a list of exactly one frame.

So a file publisher's parameter is ALWAYS a list, and the body always folds it.
`concat` of a one-element list is that element; writing it this way means the
body does not change if the path later grows a wildcard.

The connection (`connections/local_file_in.yaml` /
    `local_file_out.yaml`) carries only a `base_path` — no credentials at
    all, which is what makes the local-file connector the one to learn the
    file-source shape on.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(paths=["customers_2024.csv"]),
    output_tables=["customers_2024"],
)
def read_fixed_path(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
