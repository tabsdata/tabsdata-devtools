#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from .rel_chain_a import rel_chain_a_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_helper_chain_relative"]
)
def pub_helper_chain_relative(t: TableFrameSpec) -> TableFrameSpec:
    rel_chain_a_function()
    return t
