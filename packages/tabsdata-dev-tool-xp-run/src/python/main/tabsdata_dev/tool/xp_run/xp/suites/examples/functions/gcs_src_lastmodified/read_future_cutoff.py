#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — GCS source: WHEN NOTHING MATCHES, which is not an error.

A cutoff in the future matches nothing, on any run — the empty-slot path, pinned
here so it is deterministic and testable.

WHAT HAPPENS: the slot arrives as an EMPTY LIST, `concat` returns `None`, and a
publisher that returns `None` publishes NO new version of that table. Downstream
functions that depend on `@NEW` versions simply do not fire, which is exactly
what "nothing arrived this run" should mean.

DO NOT return an empty frame instead. That publishes a real, empty version and
DOES trigger downstream work — a different thing, and rarely the one you want.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.gcs import GCSSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=GCSSrc(
        paths=["parquet/city_*.parquet"],
        initial_last_modified=datetime(2999, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["city_none"],
)
def read_future_cutoff(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
