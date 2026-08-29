#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .entry_sibling import entry_sibling_function
from .entry_deep import entry_deep_function
from entry_pkg.entry_sibling import entry_sibling_function as entry_sibling_abs


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_nested_entry_same_level"]
)
def pub_nested_entry_same_level(t: TableFrameSpec) -> TableFrameSpec:
    entry_sibling_function()
    entry_deep_function()
    entry_sibling_abs()
    return t
