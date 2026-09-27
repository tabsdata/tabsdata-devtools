#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mysqlcdc_initial_load — the MySQL CDC stream source with ``initial_load``.

A stream publisher over EVERY table of the ``employees`` model (departments,
employees, dept_emp, dept_manager, titles, salaries, and its xp_sentinel), started with
``initial_load=True``: the stream first emits a full snapshot of each tracked table --
its rows as inserts (``@td.cdc.meta.op`` = ``i``), preceded by a LOAD control row per
table -- and then reads the binlog from the position the snapshot is consistent at.
``start_from`` is not allowed with it. The position is pinned under a brief global read
lock (``FLUSH TABLES WITH READ LOCK``, hence the domain user's RELOAD grant), held only
while the GTID set is read, not while the tables are scanned; the server runs
``gtid_mode=ON`` and the model's tables are InnoDB, as an initial load requires.

``xp_sentinel`` is the model's sentinel entity: a suite writes keys into it with ``tdd
domain sentinel-data`` and waits for them to arrive in ``xp_sentinel_changes`` (an xp
``sentinel`` stage), which is how it knows the changes before a key have flushed.

Two functions, one per suite, identical but for the collection that holds each -- and
so its connection: ``server_id`` lives on the connection and MySQL admits one replica
per id, so the two suites use their own (mysql_cdc_812.yaml, mysql_cdc_813.yaml) and
can run at the same time:

- ``mysqlcdc_initial_load``      : suite ``mysqlcdc_initial_load`` -- the snapshot is
                                   taken over quiet tables: the load is the whole seed
                                   and the changes after it are one modify-data pass.
- ``mysqlcdc_initial_load_live`` : suite ``mysqlcdc_initial_load_live`` -- modify-data
                                   keeps changing the tables from before the project
                                   exists, so the snapshot is taken over tables
                                   changing under it and the changes after it arrive
                                   as CDC rows; a deleted employee's rows in dept_emp,
                                   dept_manager, titles and salaries go too (ON DELETE
                                   CASCADE), each its own row event in the binlog.

Registering a stream publisher STARTS it (no trigger); the snapshot is its first work.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Unqualified: MySQL resolves them against the connection's database, the domain's.
_TABLES = [
    "departments",
    "employees",
    "dept_emp",
    "dept_manager",
    "titles",
    "salaries",
]
_OUTPUT = [
    "departments_changes",
    "employees_changes",
    "dept_emp_changes",
    "dept_manager_changes",
    "titles_changes",
    "salaries_changes",
]
# Every model's sentinel entity: empty until `tdd domain sentinel-data` writes a key.
_SENTINEL_TABLE = "xp_sentinel"
_SENTINEL_OUTPUT = "xp_sentinel_changes"

# Small thresholds so a handful of changes flush promptly instead of sitting in the
# buffer; poll every second so the loop reacts quickly.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": 10,
    "tabsdata.cdc.poll_interval_seconds": 1,
    "mysql.cdc.blocking_timeout_seconds": 5,
}


def _source() -> MySQLCdcStreamSrc:
    return MySQLCdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        initial_load=True,
        src_cfg=_CFG,
    )


# One slot per tracked table, each an ARRAY of the frames that flush carried; `concat`
# drops None entries and returns None for an empty list, so it doubles as the "this
# flush carried nothing for this table" guard.
@stream_publisher(
    source=_source(),
    flush_interval_mins=1,
    output_tables=[*_OUTPUT, _SENTINEL_OUTPUT],
)
def mysqlcdc_initial_load(
    departments: TableFramesSpec,
    employees: TableFramesSpec,
    dept_emp: TableFramesSpec,
    dept_manager: TableFramesSpec,
    titles: TableFramesSpec,
    salaries: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return (
        concat(departments),
        concat(employees),
        concat(dept_emp),
        concat(dept_manager),
        concat(titles),
        concat(salaries),
        concat(xp_sentinel),
    )


@stream_publisher(
    source=_source(),
    flush_interval_mins=1,
    output_tables=[*_OUTPUT, _SENTINEL_OUTPUT],
)
def mysqlcdc_initial_load_live(
    departments: TableFramesSpec,
    employees: TableFramesSpec,
    dept_emp: TableFramesSpec,
    dept_manager: TableFramesSpec,
    titles: TableFramesSpec,
    salaries: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> tuple[
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
    TableFrameSpec,
]:
    return (
        concat(departments),
        concat(employees),
        concat(dept_emp),
        concat(dept_manager),
        concat(titles),
        concat(salaries),
        concat(xp_sentinel),
    )
