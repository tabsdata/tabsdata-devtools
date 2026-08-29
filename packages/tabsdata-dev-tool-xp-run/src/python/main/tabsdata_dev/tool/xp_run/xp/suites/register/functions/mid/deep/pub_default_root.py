#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .shared_deep import deep_level_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_default_root"]
)
def pub_default_root(t: TableFrameSpec) -> TableFrameSpec:
    deep_level_function()
    return t
