#
# Copyright 2026 Tabsdata Inc.
#

"""caps_postgrescdc_initial_load — the PostgreSQL CDC stream source with ``initial_load``.

A stream publisher over the tables of the ``employeescdc`` model -- one table per way a
row is identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a
composite primary key), ``devices`` (no primary key, a unique index), ``readings``
(no primary key and no index) -- and its xp_sentinel, but NOT ``audit``, which every
data command changes too: the database is busy with a table the stream must leave
out (``verify_cdc_ops.py --untracked audit``). Started with
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

Two functions, identical -- each suite's domain brings its own slot, and each suite
its own project, so one function serves several (``gen_suites.py`` writes them):

- ``postgrescdc_initial_load``      : the snapshot is taken over quiet tables --
                                      ``postgrescdc_initial_load`` (over the seed),
                                      ``postgrescdc_from_empty`` (over empty tables,
                                      the seed arriving as a change),
                                      ``postgrescdc_quiet_table`` and
                                      ``postgrescdc_pause_resume`` (disabled and
                                      enabled three times: the stream state records
                                      the load as done, so it is not taken again, and
                                      capture resumes from the saved offset).
- ``postgrescdc_initial_load_live`` : ``postgrescdc_initial_load_live_<mode>`` -- a live
                                      stage keeps changing the tables (modify-data Mix,
                                      20 passes, ``--trx-mode serial|interleaved|nested|
                                      mix``) from before the project exists, so the
                                      snapshot is taken over tables changing under it
                                      and the changes after it arrive as CDC rows. A
                                      second sentinel, written once the churn has ended,
                                      arrives after its last change. A change committing
                                      as the snapshot is taken may arrive twice (reuse).

The postgrescdc system runs ``wal_level=logical``, installs wal2json, grants the domain
owner REPLICATION and sets REPLICA IDENTITY FULL on every model table -- which is what
lets ``devices`` and ``readings``, with no primary key, log their updates and deletes at
all, and gives every change a full before-image. Registering a stream publisher STARTS
it (no trigger); the snapshot is its first work. The domain's slot pins WAL until the
domain is destroyed, which ends any reader still on it and drops it.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher

# noinspection PyProtectedMember
from tabsdatak._api import unsafe_seconds
from tabsdatak.conn.postgres import PostgresCdcStreamSrc
from tabsdatak.tableframe.functions import concat

# Schema-qualified, as the source asks: each domain is its own database, and the model
# is installed in its `public` schema.
_TABLES = [
    "public.accounts",
    "public.ledger",
    "public.devices",
    "public.readings",
]
_OUTPUT = [
    "accounts_changes",
    "ledger_changes",
    "devices_changes",
    "readings_changes",
]
# Every model's sentinel entity: empty until `tdd domain sentinel-data` writes a key.
_SENTINEL_TABLE = "public.xp_sentinel"
_SENTINEL_OUTPUT = "xp_sentinel_changes"

# Small thresholds so a handful of changes flush promptly instead of sitting in the
# buffer; poll every second so the loop reacts quickly.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.poll.idle_secs": 1,
    "tabsdata.cdc.poll.max_secs": 5,
}


# The D0 domain's own replication slot, created with the domain and dropped with it.
_SLOT = "${D0__REPLICATION_SLOT}"


def _source(cfg: dict = _CFG) -> PostgresCdcStreamSrc:
    return PostgresCdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        replication_slot=_SLOT,
        replication_slot_behavior="reuse",
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
def postgrescdc_initial_load(
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
def postgrescdc_initial_load_live(
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
