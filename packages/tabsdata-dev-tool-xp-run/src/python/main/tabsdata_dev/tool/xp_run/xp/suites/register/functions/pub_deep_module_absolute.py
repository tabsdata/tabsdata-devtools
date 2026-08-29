#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from nested.deep.deep_module import deep_module_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_deep_module_absolute"]
)
def pub_deep_module_absolute(t: TableFrameSpec) -> TableFrameSpec:
    deep_module_function()
    return t
