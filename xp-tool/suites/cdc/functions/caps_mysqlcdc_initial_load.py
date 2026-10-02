#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mysqlcdc_initial_load — the MySQL CDC stream source with ``initial_load``.

A stream publisher over every table of the ``employeescdc`` model but ``audit`` (which
every data command changes too: ``verify_cdc_ops.py --untracked audit``) -- one table per way a
row is identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a
composite primary key), ``devices`` (no primary key, a unique index), ``readings``
(no primary key and no index) -- and its xp_sentinel, started with
``initial_load=True``: the stream first emits a full snapshot of each tracked table --
its rows as inserts (``@td.cdc.meta.op`` = ``i``), preceded by a LOAD control row per
table -- and then reads the binlog from the position the snapshot is consistent at.
``start_from`` is not allowed with it. The position is pinned under a brief global read
lock (``FLUSH TABLES WITH READ LOCK``, hence the domain user's RELOAD grant), held only
while the GTID set is read, not while the tables are scanned; the server runs
``gtid_mode=ON`` and the model's tables are InnoDB, as an initial load requires. The
binlog carries full row images (``binlog_row_image=FULL``), so a change to a table
without a key still names its row by every column.

``xp_sentinel`` is the model's sentinel entity: a suite writes keys into it with ``tdd
domain sentinel-data`` and waits for them to arrive in ``xp_sentinel_changes`` (an xp
``sentinel`` stage), which is how it knows the changes before a key have flushed.

Two functions, identical but for the live one's 30s trigger, each serving several suites
(``gen_suites.py`` writes them). Every suite's collection has a connection of its own:
``server_id`` lives on the connection and MySQL admits one replica per id, so each
uses one of the 81x templates (mysql_cdc_812.yaml to mysql_cdc_819.yaml) and all can
run at the same time:

- ``mysqlcdc_initial_load``      : the snapshot is taken over quiet tables --
                                   ``mysqlcdc_initial_load`` (over the seed),
                                   ``mysqlcdc_from_empty`` (over empty tables),
                                   ``mysqlcdc_quiet_table`` and
                                   ``mysqlcdc_pause_resume`` (enabled again, it
                                   resumes from its saved GTID set; the load is not
                                   taken again).
- ``mysqlcdc_initial_load_live`` : ``mysqlcdc_initial_load_live_<mode>`` -- modify-data
                                   keeps changing the tables from before the project
                                   exists, ``--trx-mode serial|interleaved|nested|mix``,
                                   so the snapshot is taken over tables changing under
                                   it and the changes after it arrive as CDC rows.

Registering a stream publisher STARTS it (no trigger); the snapshot is its first work.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher

# noinspection PyProtectedMember
from tabsdatak.conn.common._stream._floor import unsafe_seconds
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Unqualified: MySQL resolves them against the connection's database, the domain's.
_TABLES = ["accounts", "ledger", "devices", "readings"]
_OUTPUT = [
    "accounts_changes",
    "ledger_changes",
    "devices_changes",
    "readings_changes",
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
    "tabsdata.cdc.trigger.max_secs": unsafe_seconds(10),
    "tabsdata.cdc.poll.idle_secs": 1,
    "tabsdata.cdc.poll.max_secs": 5,
}


# Under live churn: a manifest at most every 30s. The trigger's seconds are also the
# floor between manifests, and a publisher run takes one manifest, about every 30s
# on a local server -- a stream closing one every 10s under steady change falls
# further behind for as long as the churn lasts.
_LIVE_CFG = {**_CFG, "tabsdata.cdc.trigger.max_secs": unsafe_seconds(30)}


def _source(cfg: dict = _CFG) -> MySQLCdcStreamSrc:
    return MySQLCdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        initial_load=True,
        src_cfg=cfg,
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
    source=_source(_LIVE_CFG),
    flush_interval_mins=1,
    output_tables=[*_OUTPUT, _SENTINEL_OUTPUT],
)
def mysqlcdc_initial_load_live(
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
