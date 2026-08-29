#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 source: A WILDCARD PATH.

A `*` is allowed in the LAST path segment only (`a/b*.csv` is fine, `a*/b.csv`
is not). Both staged customer files match here, so the single slot carries two
frames and `concat` unions them into the one output table.

TWO THINGS TO GET RIGHT:

  * A WILDCARD IS A PREFIX MATCH. `customers_*` would also match
    `customers_archive_*` if such a file appeared. Pick a pattern nothing else
    can grow into, or accept whatever turns up.
  * `concat` defaults to `how="vertical"`, which REQUIRES identical schemas and
    fails loudly otherwise — the right default, because a file that does not fit
    the others is usually a mistake. Use `how="diagonal"` when the match set is
    genuinely heterogeneous: it takes the union of the columns and nulls the gaps.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.s3 import S3Src
from tabsdatak.tableframe.functions import concat


@publisher(
    source=S3Src(paths=["customers_*.csv"]),
    output_tables=["customers_all"],
)
def read_wildcard(customers: TableFramesSpec) -> TableFrameSpec:
    return concat(customers)
