#
# Copyright 2026 Tabsdata Inc.
#

"""caps_postgrescdc — exercise the PostgreSQL CDC stream source (``@stream_publisher``).

Unlike every other source in this dir these are STREAM publishers, not batch ones:
each is a long-lived logical-decoding consumer (wal2json) that stays running and
closes a batch whenever the source's buffer/trigger thresholds fire (or
``flush_interval_mins`` rolls the window over). One input slot per tracked table
(``cardinality = len(tables)``), each slot an ARRAY of the frames that flush carried,
and NO ``ctx`` parameter (a stream publisher runs in the runtime's stream loop, not
per transaction).

The suite tracks the ``employees`` model's two mutable tables (``employees`` supports
INSERT/UPDATE/DELETE, ``departments`` UPDATE), so ``tdx-domain modify-data`` on the
backing domain produces the full change-op mix for the stream to capture. The
postgrescdc system already runs ``wal_level=logical``, installs wal2json, grants the
domain owner REPLICATION and sets REPLICA IDENTITY FULL on every model table, so
UPDATE/DELETE records carry complete before-images.

NO TRIGGER IS INVOLVED: registering a stream publisher STARTS it. The worker comes up
seconds after ``create-project`` and runs until the function is disabled or deleted, so
every variant below is live the moment the suite is created (``tdk worker list`` shows
them; they carry no execution plan or transaction).

REPLICATION SLOTS: the domain does NOT pre-create any, so every variant declares its
OWN slot with ``replication_slot_behavior="create"`` (create, no-op if it exists).
A slot admits ONE active consumer, and all four variants run concurrently, so the
per-variant slots are what keeps them from fighting (each variant also sits in its own
collection). Slots are per-database and each domain is its own database, so they never
collide across domains — but they DO hold WAL until consumed: drop them
(``SELECT pg_drop_replication_slot('td_cdc_base')``) if you abandon a run rather than
leaving the server pinning WAL.

Variants (see the suite's _comment for how to drive them):
- ``postgrescdc_in``        : base — ``start_from="tail"``, ``columns_format="columns"``
                              + ``flatten_columns=True`` -> ordinary tabular change rows.
- ``postgrescdc_in_head``   : ``start_from="head"`` — the oldest WAL the slot still
                              retains. NOTE logical decoding cannot reach back past slot
                              creation, so unlike MySQL/Db2 this does NOT replay the
                              create-data seed; it differs from "tail" only for changes
                              made while the consumer was away.
- ``postgrescdc_in_struct`` : ``columns_format="struct"`` + ``flatten_columns=False`` —
                              new and old column payloads arrive as nested structs.
- ``postgrescdc_in_map``    : ``columns_format="map"`` with the new columns still inlined,
                              so only the old-values payload becomes a map.

``publication_name`` is not exercised: the domain creates no publication, so the slot
streams every tracked table without one.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.postgres import PostgresCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Unqualified names: Postgres resolves them against the connection's current_schema()
# (`public` for these domains), so the same function works whatever DB the domain got.
_TABLES = ["employees", "departments"]

# Small thresholds so a handful of `modify-data` changes flush promptly instead of
# sitting in the buffer; poll every second so the loop reacts quickly.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": 10,
    "tabsdata.cdc.poll_interval_seconds": 1,
    "postgres.cdc.blocking_timeout_seconds": 5,
}


# `concat` drops None entries and returns None for an empty/None list, so it doubles as
# the "this flush carried nothing for this slot" guard. Vertical (strict) on purpose: a
# mid-stream schema change should surface here rather than be absorbed silently.
@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot="td_cdc_base",
        replication_slot_behavior="create",
        start_from="tail",
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def postgrescdc_in(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (concat(employees), concat(departments))


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot="td_cdc_head",
        replication_slot_behavior="create",
        start_from="head",
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def postgrescdc_in_head(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Oldest WAL the slot retains — which begins at slot creation, NOT at the seed load.
    return (concat(employees), concat(departments))


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot="td_cdc_struct",
        replication_slot_behavior="create",
        start_from="tail",
        columns_format="struct",
        flatten_columns=False,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def postgrescdc_in_struct(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # Not flattened: the row's new/old values stay nested under struct columns.
    return (concat(employees), concat(departments))


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=_TABLES,
        replication_slot="td_cdc_map",
        replication_slot_behavior="create",
        start_from="tail",
        columns_format="map",
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def postgrescdc_in_map(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # flatten_columns defaults to True, so the format only shapes the OLD values.
    return (concat(employees), concat(departments))
