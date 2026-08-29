#
# Copyright 2026 Tabsdata Inc.
#
import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data


@publisher(
    source=DataGenSrc(
        data=[Data(pl.DataFrame({"a": [1, 2, 3], "b": [4.5, 5.5, 6.5]}))]
    ),
    output_tables=["t"]
)
def test_pub(t: TableFrameSpec) -> TableFrameSpec:
    return t
