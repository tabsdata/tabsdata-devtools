#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · src · cdc — CDC bootstrap-snapshot + binlog/WAL stream publishers.

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, stream_publisher
from tabsdatak.conn.db2 import Db2CdcStreamSrc, Db2Src
from tabsdatak.tableframe.functions import concat


@publisher(
    source=Db2Src(queries=["SELECT tenant_id AS \"tenant_id\", entity_id AS \"entity_id\", data_ts AS \"data_ts\", name AS \"name\", status AS \"status\", category AS \"category\", amount AS \"amount\", quantity AS \"quantity\", score AS \"score\", is_active AS \"is_active\" FROM brz_full_snapshot"]),
    output_tables=["cdc_full_raw"],
)
def pub_cdc_full(df: TableFrameSpec) -> TableFrameSpec:
    # Bootstrap: a full snapshot of the tracked table. `build_cdc_bronze` uses
    # the latest full commit to erase-and-reseed bronze; the CDC stream then
    # layers I/U/D events on top.
    return df


@stream_publisher(
    source=Db2CdcStreamSrc(tables=["brz_full_snapshot"], start_from="tail"),
    batch_max_secs=120,
    output_tables=["cdc_raw"],
)
def pub_cdc_stream(df: TableFramesSpec) -> TableFrameSpec:
    # A stream publisher receives the flushed batch as a list of frames; concat
    # them into one commit. `start_from="tail"` reads only changes made after the
    # stream starts, so against a static seed this stays empty (the bootstrap
    # snapshot alone drives the bronze). Registered but not auto-triggered.
    return concat(df)
