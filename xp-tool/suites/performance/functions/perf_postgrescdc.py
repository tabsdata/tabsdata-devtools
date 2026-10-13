#
# Copyright 2026 Tabsdata Inc.
#

"""perf_postgrescdc — the PostgreSQL CDC stream source under a million rows.

Two stream publishers over the four tables of the ``employeescdc`` model, one per
suite; ``scripts/cdc_throughput.py`` measures how fast they write their files:

- ``postgrescdc_initial_load`` : ``start_from="full"`` over tables already holding
                                 the rows -- the snapshot is the whole load.
- ``postgrescdc_changes``      : from the head, after the rows are inserted -- every
                                 row a change decoded from the WAL, read as a backlog.

Both read over the domain's own replication slot (``${D0__REPLICATION_SLOT}``,
created with the domain and dropped with it), so they REUSE it. The slot holds
the WAL from its creation, before the model and its rows: that is what the head
replays, so the million inserts are all there when the stream starts.

The thresholds are raised for a large run -- a few large files and versions, not
many small ones (see ``_CFG``).
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.postgres import PostgresCdcStreamSrc
from tabsdatak.tableframe.functions import concat

_TABLES = ["accounts", "ledger", "devices", "readings"]
_OUTPUT = ["accounts_changes", "ledger_changes", "devices_changes", "readings_changes"]
_SLOT = "${D0__REPLICATION_SLOT}"
# Rows count across every tracked table. A buffer spills as one file per table
# and a trigger publishes the spilled files as a version, so large row limits make
# a few large files and versions rather than many small ones -- ~50k rows a table
# a file, ~2 versions a table for a million rows. The buffer's time limit is what
# the LAST partial buffer waits before it is written, and that wait ends the
# measured time: short, so it does not swamp a backlog read in seconds (the row
# limit fills well before it while one streams in). The trigger's limits come
# after the files, outside what is measured.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 200_000,
    "tabsdata.cdc.buffer.max_secs": 2,
}

_Out4 = tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot=_SLOT,
        replication_slot_behavior="reuse",
        start_from="full",
        src_cfg=_CFG,
    ),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def postgrescdc_initial_load(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot=_SLOT,
        replication_slot_behavior="reuse",
        start_from="head",
        src_cfg=_CFG,
    ),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def postgrescdc_changes(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)
