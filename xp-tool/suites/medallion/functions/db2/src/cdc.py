#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · src · cdc — CDC stream publisher with an initial load.

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_cdc_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.db2 import Db2CdcStreamSrc
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source=Db2CdcStreamSrc(tables=["${D0__CD_TABLE_PREFIX}BRZ_FULL_SNAPSHOT"], start_from="full"),
    batch_max_secs=120,
    output_tables=["cdc_raw"],
)
def pub_cdc_stream(df: TableFramesSpec) -> TableFrameSpec:
    # `start_from="full"` makes the stream start with an `l` (load) row and a
    # snapshot of the table as inserts, then capture changes from the exact log
    # position of that snapshot. To resync later, reset the function's stage
    # (`tdk fn update --reset-stage`). A stream publisher receives the flushed
    # batch as a list of frames; concat them into one commit. Db2 reports the
    # unquoted columns upper-cased, so the data columns are lower-cased to match
    # the other systems; the `@td.*` / `$td.*` metadata columns keep their names.
    tf = concat(df)
    return tf.rename({c: c.lower() for c in tf.columns if not c.startswith(("@", "$"))})
