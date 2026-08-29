#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 source: NO CUTOFF, the full-reload contrast.

Without `initial_last_modified` every matched file is read on every run. That is
the right choice for a small reference dataset that is replaced wholesale, and
the wrong one for an append-only landing zone — where it means re-reading the
entire history to learn about one new file.

Run this suite twice and compare with `read_since_cutoff`: this table is rebuilt
from everything, that one grows by what arrived.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.s3 import S3Src
from tabsdatak.tableframe.functions import concat


@publisher(
    source=S3Src(paths=["parquet/city_*.parquet"]),
    output_tables=["city_all"],
)
def read_every_run(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
