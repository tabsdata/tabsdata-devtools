#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. Writes the lines out as `app.log`.

A ONE-COLUMN CSV WITH NO HEADER **IS** A TEXT FILE. `include_header: False` drops
the header row and the separator never appears in the data, so every line is
written exactly as it came in — which gives the reader something honest to treat
as a log.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.common.file.typing_ import DestFileFormat
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(
        paths=["app.log"],
        format=DestFileFormat.CSV,
        format_cfg={DestFileFormat.CSV: {"include_header": False, "separator": ";"}},
    ),
    input_tables=["gen/raw_lines"],
)
def stage_log_file(lines: TableFrameSpec) -> TableFrameSpec:
    return lines
