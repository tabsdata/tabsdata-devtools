#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — SOURCE METADATA: what a file source records about where a row came
from, and how to keep it.

EVERY SOURCE STAMPS METADATA onto the tables it publishes, under the reserved
`@td.` prefix. You do not ask for it; it is the default. What varies is WHAT each
source has to say:

    file (localfile / s3 / gcs / azureblob)
        `@td.file.path`             the path or object URI the row was read from
    SQL (postgres / mysql / mssql / oracle / db2 / databricks)
        `@td.sql.query`             the text of the query that produced the row
        `@td.sql.initial_values`    the binds it ran with, as JSON
    kafka
        `@td.kafka.topic`           the topic the message came from
    salesforce (SOQL)
        `@td.salesforce.soql`       the query as sent, `$lastModified` resolved
        `@td.salesforce.last_modified`  the cutoff it ran with
    salesforce (report)
        `@td.salesforce.report_id`  the RESOLVED report id, even when named
    CDC (postgres / mysql / db2)
        `@td.cdc.meta.op` / `.tx` / `.sq` / `.ts` / `.ord` / `.sch` / ...

WHY IT MATTERS MOST ON A WILDCARD. This publisher reads `parquet/*.parquet` —
three entities, folded into one table by a diagonal `concat`. Without
`@td.file.path` the result is a heap of rows with no way back to the file each
came from; with it, provenance survives the union, and "which file had the bad
row" is a filter rather than an investigation.

The same argument applies to a multi-query SQL source: `@td.sql.query` is what
tells two unioned result sets apart afterwards.

`read_file_metadata_dropped.py` is the same read with the metadata turned off.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    # No `src_cfg`: metadata is on by default.
    source=LocalFileSrc(paths=["parquet/*.parquet"]),
    output_tables=["world_with_metadata"],
)
def read_file_metadata(matches: TableFramesSpec) -> TableFrameSpec:
    # Diagonal, because the three world entities have different schemas — the
    # union of the columns, gaps nulled. See s3_src/read_prefix.py.
    return concat(matches, how="diagonal")
