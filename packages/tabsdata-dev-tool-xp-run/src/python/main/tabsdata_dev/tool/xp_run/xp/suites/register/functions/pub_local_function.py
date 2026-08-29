#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data


def local_function():
    print("local_function()")
    pass


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_local_function"]
)
def pub_local_function(t: TableFrameSpec) -> TableFrameSpec:
    local_function()
    return t
