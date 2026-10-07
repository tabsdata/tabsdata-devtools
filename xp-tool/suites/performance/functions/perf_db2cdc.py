#
# Copyright 2026 Tabsdata Inc.
#

"""perf_db2cdc — the Db2 CDC stream source under a million rows.

Two stream publishers over the four tables of the ``employeescdc`` model, one per
suite; ``scripts/cdc_throughput.py`` measures how fast they write their files:

- ``db2cdc_initial_load`` : ``initial_load=True`` over tables already holding the
                            rows -- the snapshot is the whole load.
- ``db2cdc_changes``      : from the head, after the rows are inserted -- every row
                            a change from the CD tables asncap fills, read as a
                            backlog: the head is each CD table's origin, and they
                            are registered with the model, before its rows.

``tables`` names the CD tables, the domain's own (``${D0__CD_TABLE_PREFIX}<TABLE>``,
upper-cased as Db2 folds unquoted names); the output tables carry Db2's upper-cased
column names.

The thresholds are raised for a large run -- a few large files and versions, not
many small ones (see ``_CFG``).
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.db2 import Db2CdcStreamSrc
from tabsdatak.tableframe.functions import concat

_TABLES = [
    "${D0__CD_TABLE_PREFIX}ACCOUNTS",
    "${D0__CD_TABLE_PREFIX}LEDGER",
    "${D0__CD_TABLE_PREFIX}DEVICES",
    "${D0__CD_TABLE_PREFIX}READINGS",
]
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
    source=Db2CdcStreamSrc(tables=_TABLES, initial_load=True, src_cfg=_CFG),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def db2cdc_initial_load(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)


@stream_publisher(
    source=Db2CdcStreamSrc(
        tables=_TABLES,
        start_from="head",
        src_cfg=_CFG,
    ),
    batch_max_secs=60,
    batch_max_rows=500_000,
    output_tables=_OUTPUT,
)
def db2cdc_changes(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
) -> _Out4:
    return concat(accounts), concat(ledger), concat(devices), concat(readings)
