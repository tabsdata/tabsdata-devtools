#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — S3 source: SEVERAL PATHS, kept as SEPARATE tables.

The same two paths as `read_multiple_paths`, and the only difference is the
FOLD: one output table per slot instead of one table for both. That is the whole
choice a multi-path source gives you.

Output tables are POSITIONAL — `output_tables[i]` takes the i-th element of the
returned tuple, which is the i-th path. A file that is a different THING (a
different entity, a different schema) belongs in its own table; a file that is
more of the same belongs in the union.

ONE SOURCE READS ONE FORMAT. `format` — including the `AUTO` default — is
resolved for the SOURCE, not per path, so a `paths` list whose entries imply
different formats is rejected before it reads anything:

    Source format=AUTO could not be inferred from paths
    ['customers_2024.csv', 'orders.parquet']: mixed formats inferred

Which is why this reads the two CSVs and not the parquet staged beside them:
`orders.parquet` needs its OWN publisher. Worth knowing before designing a
landing zone that mixes formats in one directory.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.s3 import S3Src
from tabsdatak.tableframe.functions import concat


@publisher(
    source=S3Src(paths=["customers_2024.csv", "customers_2025.csv"]),
    output_tables=["customers_first", "customers_second"],
)
def read_multiple_paths_split(
    year_2024: TableFramesSpec,
    year_2025: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (concat(year_2024), concat(year_2025))
