#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TURNING SOURCE METADATA OFF: `tabsdata.src_metadata.drop`.

One `src_cfg` key, supported by every source that stamps metadata:

    src_cfg={"tabsdata.src_metadata.drop": True}

It is all-or-nothing per source — there is no way to keep `@td.sql.query` and
drop `@td.sql.initial_values`. If you want a subset, keep them all and project
the ones you want in the next transform.

WHEN TO DROP IT

  * The table is a PUBLIC CONTRACT and `@td.` columns would leak how it was
    produced — the query text, a file path with a username in it, an object URI
    naming an internal bucket. `@td.sql.query` in particular is a small
    information disclosure if the table is shared widely.
  * The value is CONSTANT and therefore worthless: a single-path read that always
    reads the same file stamps the same string on every row, and you are paying
    for it once per row.
  * You are about to `concat` frames from sources whose metadata differs, and
    would rather have a clean schema than a diagonal one.

WHEN NOT TO

  * Anything that fans in — a wildcard, a multi-query read, a Kafka topic set.
    That is exactly where provenance is worth its width.
  * Anything you will have to debug in production. Dropping metadata is cheap to
    undo in code and expensive to undo in an incident.

Same read as `read_file_metadata.py`, so the two tables differ in exactly one
thing.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(
        paths=["parquet/*.parquet"],
        src_cfg={"tabsdata.src_metadata.drop": True},
    ),
    output_tables=["world_without_metadata"],
)
def read_file_metadata_dropped(matches: TableFramesSpec) -> TableFrameSpec:
    return concat(matches, how="diagonal")
