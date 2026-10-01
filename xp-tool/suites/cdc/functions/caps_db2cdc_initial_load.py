#
# Copyright 2026 Tabsdata Inc.
#

"""caps_db2cdc_initial_load — the Db2 CDC stream source with ``initial_load``.

A stream publisher over EVERY table of the ``employeescdc`` model -- one table per way a
row is identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a
composite primary key), ``devices`` (no primary key, a unique index), ``readings``
(no primary key and no index) -- and its xp_sentinel, started with
``initial_load=True``: the stream first emits a full snapshot of each tracked SOURCE
table -- its rows as inserts (``@td.cdc.meta.op`` = ``i``), preceded by a LOAD control
row per table -- and then reads the CD tables from the commit sequence the snapshot is
consistent at. ``start_from`` is not allowed with it. ``tables`` still names the CD
tables (``${D0__CD_TABLE_PREFIX}<TABLE>``, the domain's own, which the db2cdc system
registers for every model table); the source behind each is resolved through
``ASN.IBMSNAP_REGISTER``, and the snapshot reads it, locking it briefly while the
capture position is read.

``xp_sentinel`` is the model's sentinel entity: a suite writes keys into it with ``tdd
domain sentinel-data`` and waits for them to arrive in ``xp_sentinel_changes`` (an xp
``sentinel`` stage), which is how it knows the changes before a key have flushed.

Two functions, one per suite, identical -- each suite's domain brings its own CD tables:

- ``db2cdc_initial_load``      : suite ``db2cdc_initial_load`` -- the snapshot is taken
                                 over quiet tables: the load is the whole seed and the
                                 changes after it are one modify-data pass.
- ``db2cdc_initial_load_live`` : suite ``db2cdc_initial_load_live`` -- modify-data keeps
                                 changing the tables from before the project exists,
                                 so the snapshot is taken over tables changing under
                                 it and the changes after it arrive as CDC rows.

The output tables carry Db2's column names, upper-cased (``ACCOUNT_ID``) as its catalog
folds unquoted identifiers, where the model has ``account_id``: the sentinel stage and
``scripts/verify_cdc_ops.py`` match columns without case. A source transaction is
Db2's 32 hex digits.

asncap stages changes in the background, so a change reaches a CD table a moment after
it commits. Registering a stream publisher STARTS it (no trigger); the snapshot is its
first work.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher

# noinspection PyProtectedMember
from tabsdatak.conn.common._stream._floor import unsafe_seconds
from tabsdatak.conn.db2 import Db2CdcStreamSrc
from tabsdatak.tableframe.functions import concat

# CD (staging) tables, not the source tables: the D0 domain's own prefix
# (ASN.TD_<tag>__), uppercased the way Db2 stores unquoted identifiers.
_TABLES = [
    "${D0__CD_TABLE_PREFIX}ACCOUNTS",
    "${D0__CD_TABLE_PREFIX}LEDGER",
    "${D0__CD_TABLE_PREFIX}DEVICES",
    "${D0__CD_TABLE_PREFIX}READINGS",
]
_OUTPUT = [
    "accounts_changes",
    "ledger_changes",
    "devices_changes",
    "readings_changes",
]
# Every model's sentinel entity: empty until `tdd domain sentinel-data` writes a key.
_SENTINEL_TABLE = "${D0__CD_TABLE_PREFIX}XP_SENTINEL"
_SENTINEL_OUTPUT = "xp_sentinel_changes"

# Small thresholds so a handful of changes flush promptly instead of sitting in the
# buffer; poll every second so the loop reacts quickly. `fetch_size` caps the
# server-side fetch when draining a CD table.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": unsafe_seconds(10),
    "tabsdata.cdc.poll_interval_seconds": 1,
    "db2.cdc.blocking_timeout_seconds": 5,
    "tabsdata.cdc.fetch_size": 500,
}


def _source() -> Db2CdcStreamSrc:
    return Db2CdcStreamSrc(
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
def db2cdc_initial_load(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (
        concat(accounts),
        concat(ledger),
        concat(devices),
        concat(readings),
        concat(xp_sentinel),
    )


@stream_publisher(
    source=_source(),
    flush_interval_mins=1,
    output_tables=[*_OUTPUT, _SENTINEL_OUTPUT],
)
def db2cdc_initial_load_live(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (
        concat(accounts),
        concat(ledger),
        concat(devices),
        concat(readings),
        concat(xp_sentinel),
    )
