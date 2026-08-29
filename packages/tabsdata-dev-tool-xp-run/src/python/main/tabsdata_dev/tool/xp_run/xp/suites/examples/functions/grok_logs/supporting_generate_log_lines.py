#
# Copyright 2026 Tabsdata Inc.
#

"""SUPPORTING — not the example. The four log lines this suite parses.

Deliberately free of commas, quotes and semicolons, so the CSV writer in
`supporting_stage_log_file.py` stages each line VERBATIM and the file that lands
is an ordinary text log.

Three lines are well-formed; the fourth is a bare restart notice that none of the
patterns in this suite matches — so every result table has a row of nulls to look
at, which is the null-on-no-match contract made visible.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "line": [
                    "2026-03-12T10:15:32Z INFO api-gateway request=8f3c "
                    "method=GET path=/api/orders status=200 duration_ms=45",
                    "2026-03-12T10:15:33Z WARN api-gateway request=8f3d "
                    "method=POST path=/api/orders status=429 duration_ms=12",
                    "2026-03-12T10:15:34Z ERROR order-service request=8f3e "
                    "method=POST path=/api/orders status=500 duration_ms=310",
                    "-- worker pool restarted --",
                ]
            }))
        ]
    ),
    output_tables=["raw_lines"],
)
def generate_log_lines(lines: TableFrameSpec) -> TableFrameSpec:
    return lines
