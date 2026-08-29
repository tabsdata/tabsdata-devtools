#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .shared_deep import deep_level_function
from shared_mid import mid_level_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_bundle_mid_mixed"]
)
def pub_bundle_mid_mixed(t: TableFrameSpec) -> TableFrameSpec:
    deep_level_function()
    mid_level_function()
    return t
