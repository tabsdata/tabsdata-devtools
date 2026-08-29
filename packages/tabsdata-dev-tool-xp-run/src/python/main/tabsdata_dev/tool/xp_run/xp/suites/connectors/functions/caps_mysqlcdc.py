#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mysqlcdc — exercise the MySQL CDC stream source (``@stream_publisher``).

Unlike every other source in this dir these are STREAM publishers, not batch ones:
each is a long-lived binlog consumer that stays running and closes a batch whenever
the source's buffer/trigger thresholds fire (or ``flush_interval_mins`` rolls the
window over). One input slot per tracked table (``cardinality = len(tables)``), each
slot an ARRAY of the frames that flush carried, and NO ``ctx`` parameter (a stream
publisher runs in the runtime's stream loop, not per transaction).

The suite tracks the ``employees`` model's two mutable tables (``employees`` supports
INSERT/UPDATE/DELETE, ``departments`` UPDATE), so ``tdx-domain modify-data`` on the
backing domain produces the full change-op mix for the stream to capture.

NO TRIGGER IS INVOLVED: registering a stream publisher STARTS it. The worker comes up
seconds after ``create-project`` and runs until the function is disabled or deleted, so
every variant below is live the moment the suite is created (``tdk worker list`` shows
them; they carry no execution plan or transaction).

Variants (see the suite's _comment for how to drive them):
- ``mysqlcdc_in``        : base — ``start_from="tail"`` (only changes made after the
                           consumer attaches), ``columns_format="columns"`` +
                           ``flatten_columns=True`` -> ordinary tabular change rows.
- ``mysqlcdc_in_head``   : ``start_from="head"`` — replays the retained binlog, so the
                           seed load done by ``create-data`` shows up as inserts
                           (the container keeps 3 days of binlog). The binlog is
                           server-wide, so this scans other domains' traffic too and
                           filters it out — expect a slower first pass.
- ``mysqlcdc_in_struct`` : ``columns_format="struct"`` + ``flatten_columns=False`` —
                           new and old column payloads arrive as nested structs.
- ``mysqlcdc_in_map``    : ``columns_format="map"`` with the new columns still inlined,
                           so only the old-values payload becomes a map.

ONE CONNECTION EACH: ``server_id`` lives on the CONNECTION, and MySQL admits a single
replica per server id — a second stream attaching with the same id disconnects the
first with ``(1236, "A replica with the same server_uuid/server_id ...")``. Since all
four run concurrently, each variant sits in its OWN collection with its own template
(mysql_cdc.yaml=512, _513, _514, _515). Ids are per MySQL SERVER, not per database, so
any other mysql-cdc collection on the same container needs an id outside that range.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Unqualified names: MySQL resolves them against the connection's default database,
# so the same function works whatever DB the domain was given.
_TABLES = ["employees", "departments"]

# Small thresholds so a handful of `modify-data` changes flush promptly instead of
# sitting in the buffer; poll every second so the loop reacts quickly.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": 10,
    "tabsdata.cdc.poll_interval_seconds": 1,
    "mysql.cdc.blocking_timeout_seconds": 5,
}


# `concat` drops None entries and returns None for an empty/None list, so it doubles as
# the "this flush carried nothing for this slot" guard. Vertical (strict) on purpose: a
# mid-stream schema change should surface here rather than be absorbed silently.
@stream_publisher(
    source=MySQLCdcStreamSrc(tables=_TABLES, start_from="tail", src_cfg=_CFG),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def mysqlcdc_in(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (concat(employees), concat(departments))


@stream_publisher(
    source=MySQLCdcStreamSrc(tables=_TABLES, start_from="head", src_cfg=_CFG),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def mysqlcdc_in_head(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Replays the binlog from the oldest retained position -> the create-data seed
    # arrives as inserts before any live change.
    return (concat(employees), concat(departments))


@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=_TABLES,
        start_from="tail",
        columns_format="struct",
        flatten_columns=False,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def mysqlcdc_in_struct(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Not flattened: the row's new/old values stay nested under struct columns.
    return (concat(employees), concat(departments))


@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=_TABLES,
        start_from="tail",
        columns_format="map",
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def mysqlcdc_in_map(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # flatten_columns defaults to True, so the format only shapes the OLD values.
    return (concat(employees), concat(departments))
