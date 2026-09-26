#
# Copyright 2026 Tabsdata Inc.
#

"""caps_postgrescdc_initial_load — the PostgreSQL CDC stream source with ``initial_load``.

A stream publisher over EVERY table of the ``employees`` model (departments,
employees, dept_emp, dept_manager, titles, salaries, and its xp_sentinel), started with
``initial_load=True``: the stream first emits a full snapshot of each tracked table --
its rows as inserts (``@td.cdc.meta.op`` = ``i``), preceded by a LOAD control row per
table -- and then captures changes from the exact position the snapshot is consistent
at, so nothing is missed between the two and nothing is repeated. ``start_from`` is
not allowed with it.

The slot is the domain's own: a postgrescdc domain creates one with its database, named
after it, and destroying the domain drops it (``${D0__REPLICATION_SLOT}``, interpolated
by xp when it registers the function). Slot names are server-wide, so one per domain is
what keeps runs against the same system apart. Since the slot exists before the function
does, the source REUSES it (``replication_slot_behavior="reuse"``): the load leaves the
slot alone, takes its snapshot in a transaction of its own and starts capture at the WAL
position of that moment. Nothing is missed; a transaction committing just as the
snapshot is taken may be delivered again. ``"create"`` would make the pair exact -- the
slot exporting snapshot and position in one operation -- but only on a slot that does
not exist yet, and one the suite would then have to drop itself.

``xp_sentinel`` is the model's sentinel entity: a suite writes keys into it with ``tdd
domain sentinel-data`` and waits for them to arrive in ``xp_sentinel_changes`` (an xp
``sentinel`` stage), which is how it knows the changes before a key have flushed.

Two functions, one per suite, identical -- each suite's domain brings its own slot:

- ``postgrescdc_initial_load``      : suite ``postgrescdc_initial_load`` -- the seed is
                                      loaded, then the snapshot is taken over quiet
                                      tables: the load is the whole seed, and no change
                                      follows it; the one sentinel, written after the
                                      seed, arrives with the snapshot.
- ``postgrescdc_initial_load_live`` : suite ``postgrescdc_initial_load_live`` -- a live
                                      stage keeps changing the tables (modify-data Mix,
                                      every 30s for ~10 min) from before the project
                                      exists, so the snapshot is taken over tables
                                      changing under it and the changes after it arrive
                                      as CDC rows. ``employees`` gets inserts, updates
                                      and deletes, ``departments`` updates; a deleted
                                      employee's rows in dept_emp, dept_manager, titles
                                      and salaries go too (ON DELETE CASCADE), so those
                                      tables see deletes after their load. A second
                                      sentinel, written once the churn has ended,
                                      arrives after its last change. A change committing
                                      as the snapshot is taken may arrive twice (reuse).

The postgrescdc system runs ``wal_level=logical``, installs wal2json, grants the domain
owner REPLICATION and sets REPLICA IDENTITY FULL on every model table, so updates and
deletes carry full before-images. Registering a stream publisher STARTS it (no
trigger); the snapshot is its first work. The domain's slot pins WAL until the domain
is destroyed, which ends any reader still on it and drops it.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.postgres import PostgresCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Schema-qualified, as the source asks: each domain is its own database, and the model
# is installed in its `public` schema.
_TABLES = [
    "public.departments",
    "public.employees",
    "public.dept_emp",
    "public.dept_manager",
    "public.titles",
    "public.salaries",
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
_SENTINEL_TABLE = "public.xp_sentinel"
_SENTINEL_OUTPUT = "xp_sentinel_changes"

# Small thresholds so a handful of changes flush promptly instead of sitting in the
# buffer; poll every second so the loop reacts quickly.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": 10,
    "tabsdata.cdc.poll_interval_seconds": 1,
    "postgres.cdc.blocking_timeout_seconds": 5,
}


# The D0 domain's own replication slot, created with the domain and dropped with it.
_SLOT = "${D0__REPLICATION_SLOT}"


def _source() -> PostgresCdcStreamSrc:
    return PostgresCdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        replication_slot=_SLOT,
        replication_slot_behavior="reuse",
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
def postgrescdc_initial_load(
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
def postgrescdc_initial_load_live(
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
