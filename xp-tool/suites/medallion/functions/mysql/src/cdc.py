#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · src · cdc — CDC bootstrap-snapshot + binlog/WAL stream publishers.

Part of the mysql medallion pipeline (source MySQL, domain mysql_bronze_xs). Collection mysql_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc, MySQLSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=MySQLSrc(queries=["SELECT tenant_id, entity_id, data_ts, name, status, category, amount, quantity, score, is_active FROM brz_full_snapshot"]),
    output_tables=["cdc_full_raw"],
)
def pub_cdc_full(df: TableFrameSpec) -> TableFrameSpec:
    # Bootstrap: a full snapshot of the tracked table. `build_cdc_bronze` uses
    # the latest full commit to erase-and-reseed bronze; the CDC stream then
    # layers I/U/D events on top.
    return df


@stream_publisher(
    source=MySQLCdcStreamSrc(tables=["brz_full_snapshot"], start_from="tail"),
    batch_max_secs=120,
    output_tables=["cdc_raw"],
)
def pub_cdc_stream(df: TableFramesSpec) -> TableFrameSpec:
    # A stream publisher receives the flushed batch as a list of frames; concat
    # them into one commit. `start_from="tail"` reads only changes made after the
    # stream starts, so against a static seed this stays empty (the bootstrap
    # snapshot alone drives the bronze). Registered but not auto-triggered.
    return concat(df)
