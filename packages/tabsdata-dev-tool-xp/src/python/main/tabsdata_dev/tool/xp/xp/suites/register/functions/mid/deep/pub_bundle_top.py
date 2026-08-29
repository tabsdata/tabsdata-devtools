#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from shared_root import root_level_function
from mid.shared_mid import mid_level_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_bundle_top"]
)
def pub_bundle_top(t: TableFrameSpec) -> TableFrameSpec:
    root_level_function()
    mid_level_function()
    return t
