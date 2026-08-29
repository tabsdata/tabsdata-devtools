#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from chain_a import chain_a_function


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_helper_chain_absolute"]
)
def pub_helper_chain_absolute(t: TableFrameSpec) -> TableFrameSpec:
    chain_a_function()
    return t
