#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from nested.nested_module import nested_module_function

@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_nested_module_absolute"]
)
def pub_nested_module_absolute(t: TableFrameSpec) -> TableFrameSpec:
    nested_module_function()
    return t
