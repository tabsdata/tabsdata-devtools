#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file source: SEVERAL PATHS, folded into ONE table.

Two `paths` entries means TWO SLOTS — the same two files the wildcard example
matches by pattern, named explicitly instead. Each slot is its own list, so
folding across them means flattening both lists into one `concat`.

Choose explicit paths over a wildcard when the set is known and small: the read
then fails when a file is missing, instead of silently returning less data.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(paths=["customers_2024.csv", "customers_2025.csv"]),
    output_tables=["customers_union"],
)
def read_multiple_paths(
    year_2024: TableFramesSpec,
    year_2025: TableFramesSpec,
) -> TableFrameSpec:
    return concat([*year_2024, *year_2025])
