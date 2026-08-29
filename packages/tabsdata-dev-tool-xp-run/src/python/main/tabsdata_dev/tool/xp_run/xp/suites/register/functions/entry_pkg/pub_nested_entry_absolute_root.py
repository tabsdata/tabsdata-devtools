#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .entry_sibling import entry_sibling_function
from nested.nested_module import nested_module_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_nested_entry_absolute_root"]
)
def pub_nested_entry_absolute_root(t: TableFrameSpec) -> TableFrameSpec:
    entry_sibling_function()
    nested_module_function()
    return t
