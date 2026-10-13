#
# Copyright 2026 Tabsdata Inc.
#

"""perf_mysqlcdc — the MySQL CDC stream source under a million rows.

Two stream publishers over the four tables of the ``employeescdc`` model, one per
suite; ``scripts/cdc_throughput.py`` measures how fast they write their files:

- ``mysqlcdc_initial_load`` : ``start_from="full"`` over tables already holding the
                              rows -- the snapshot is the whole load.
- ``mysqlcdc_changes``      : from the head, after the rows are inserted -- every row
                              a change read from the binlog, as a backlog. The head
                              is the oldest binlog the server keeps, the whole
                              container's: what earlier runs left is read and skipped
                              too, and counts in the time.

Each stream is a replica of its own, so its connection carries a ``server_id`` of its
own: ``connections/mysql_cdc_912.yaml`` and ``_913``.

The thresholds are raised for a large run -- a few large files and versions, not
many small ones (see ``_CFG``).
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat

_TABLES = ["accounts", "ledger", "devices", "readings"]
_OUTPUT = ["accounts_changes", "ledger_changes", "devices_changes", "readings_changes"]
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
    source=MySQLCdcStreamSrc(tables=_TABLES, start_from="full", src_cfg=_CFG),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def mysqlcdc_initial_load(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)


@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=_TABLES, start_from="head", src_cfg=_CFG
    ),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def mysqlcdc_changes(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)
