#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · src · cdc — CDC stream publisher with an initial load.

Part of the mysql medallion pipeline (source MySQL, domain mysql_bronze_xs). Collection mysql_in_cdc_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source=MySQLCdcStreamSrc(tables=["brz_full_snapshot"], start_from="full"),
    batch_max_secs=120,
    output_tables=["cdc_raw"],
)
def pub_cdc_stream(df: TableFramesSpec) -> TableFrameSpec:
    # `start_from="full"` makes the stream start with an `l` (load) row and a
    # snapshot of the table as inserts, then capture changes from the exact log
    # position of that snapshot. To resync later, reset the function's stage
    # (`tdk fn update --reset-stage`). A stream publisher receives the flushed
    # batch as a list of frames; concat them into one commit.
    return concat(df)
