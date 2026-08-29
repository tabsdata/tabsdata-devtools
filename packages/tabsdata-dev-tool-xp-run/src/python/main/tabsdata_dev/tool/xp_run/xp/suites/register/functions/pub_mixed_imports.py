#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .side_module import side_module_function
from nested.nested_module import nested_module_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_mixed_imports"]
)
def pub_mixed_imports(t: TableFrameSpec) -> TableFrameSpec:
    side_module_function()
    nested_module_function()
    return t
