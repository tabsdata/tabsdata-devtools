#
# Copyright 2026 Tabsdata Inc.
#
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import DataGenSrc, Data

from datetime import datetime, timedelta
from collections import OrderedDict


class LocalMarker:
    stamp = datetime(2020, 1, 1)
    window = timedelta(days=1)
    cache: OrderedDict = OrderedDict()


@publisher(
    source=DataGenSrc(data=[Data(pl.DataFrame({"a": []}))]),
    output_tables=["t_imports_builtin_type"]
)
def pub_imports_builtin_type(t: TableFrameSpec) -> TableFrameSpec:
    _ = LocalMarker.stamp
    return t
