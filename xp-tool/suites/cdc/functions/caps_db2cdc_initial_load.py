#
# Copyright 2026 Tabsdata Inc.
#

"""caps_db2cdc_initial_load — the Db2 CDC stream source with ``initial_load``.

A stream publisher over every table of the ``employeescdc`` model but ``audit`` (which
every data command changes too: ``verify_cdc_ops.py --untracked audit``) -- one table per way a
row is identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a
composite primary key), ``devices`` (no primary key, a unique index), ``readings``
(no primary key and no index) -- and its xp_sentinel, started with
``initial_load=True``: the stream first emits a full snapshot of each tracked SOURCE
table -- its rows as inserts (``@td.cdc.meta.op`` = ``i``), preceded by a LOAD control
row per table -- and then reads the CD tables from the commit sequence the snapshot is
consistent at. ``start_from`` is not allowed with it. ``tables`` still names the CD
tables (``${D0__CD_TABLE_PREFIX}<TABLE>``, the domain's own, which the db2cdc system
registers for every model table); the source behind each is resolved through
``ASN.IBMSNAP_REGISTER``, and the snapshot reads it under cursor stability, locking no
table: the log position is read first, so a change committed while the rows are read
may be both loaded and replayed, never lost.

``xp_sentinel`` is the model's sentinel entity: a suite writes keys into it with ``tdd
domain sentinel-data`` and waits for them to arrive in ``xp_sentinel_changes`` (an xp
``sentinel`` stage), which is how it knows the changes before a key have flushed.

Two functions, identical but for the live one's 30s trigger -- each suite's domain
brings its own CD tables, so one function serves several (``gen_suites.py`` writes them):

- ``db2cdc_initial_load``      : the snapshot is taken over quiet tables --
                                 ``db2cdc_initial_load`` (over the seed),
                                 ``db2cdc_from_empty`` (over empty tables),
                                 ``db2cdc_quiet_table`` and ``db2cdc_pause_resume``
                                 (enabled again, it resumes each CD table from its
                                 saved commit sequence; the load is not taken again).
- ``db2cdc_initial_load_live`` : ``db2cdc_initial_load_live_<mode>`` -- modify-data
                                 keeps changing the tables from before the project
                                 exists, ``--trx-mode serial|interleaved|nested|mix``,
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
from tabsdatak._api import unsafe_seconds
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
    "tabsdata.cdc.poll.idle_secs": 1,
    "tabsdata.cdc.poll.max_secs": 5,
    "tabsdata.cdc.fetch_size": 500,
}


def _source(cfg: dict = _CFG) -> Db2CdcStreamSrc:
    return Db2CdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        initial_load=True,
        src_cfg=cfg,
    )


# One slot per tracked table, each an ARRAY of the frames that flush carried; `concat`
# drops None entries and returns None for an empty list, so it doubles as the "this
# flush carried nothing for this table" guard.
@stream_publisher(
    source=_source(),
    batch_min_secs=unsafe_seconds(10),
    batch_max_secs=unsafe_seconds(10),
    batch_max_rows=10,
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


# Under live churn: a batch at most every 30s. The batch's seconds are also the
# floor between batches, and a publisher run takes one batch, about every 30s
# on a local server -- a stream closing one every 10s under steady change falls
# further behind for as long as the churn lasts (a nested lane once had its last
# batch published 4.5 minutes after it was staged).
@stream_publisher(
    source=_source(),
    batch_min_secs=unsafe_seconds(30),
    batch_max_secs=unsafe_seconds(30),
    batch_max_rows=10,
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
