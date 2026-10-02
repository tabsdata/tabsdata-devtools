#
# Copyright 2026 Tabsdata Inc.
#

"""caps_db2cdc — exercise the Db2 CDC stream source (``@stream_publisher``).

Unlike every other source in this dir these are STREAM publishers, not batch ones:
each is a long-lived consumer of Db2 SQL Replication's CD (change-data) tables, which
the ASN capture program (``asncap``) fills in the background. Each stays running and
closes a batch whenever the source's buffer/trigger thresholds fire (or
``flush_interval_mins`` rolls the window over). One input slot per tracked table
(``cardinality = len(tables)``), each slot an ARRAY of the frames that flush carried,
and NO ``ctx`` parameter (a stream publisher runs in the runtime's stream loop, not
per transaction).

``tables`` lists the CD TABLES, not the source tables — the ingester resolves the
source through ``ASN.IBMSNAP_REGISTER``. The db2cdc system registers every model table
at DDL-install time and stages it as ``ASN.TD_<tag>__<TABLE>`` (uppercased, since Db2
folds unquoted identifiers), <tag> taken from the domain's schema: the ASN schema is
shared, so the CD tables carry the domain in their name, and any number of db2cdc domains
of one model share a system. The domain records the prefix as ``CD_TABLE_PREFIX``, which
xp puts in for ``${D0__CD_TABLE_PREFIX}`` below when it registers the function.

The suite tracks every table of the ``employeescdc`` model -- one table per way a row is
identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a composite
primary key), ``devices`` (no primary key, a unique index), ``readings`` (no primary
key and no index) -- and its xp_sentinel, so ``tdd domain modify-data`` on the backing
domain produces inserts, updates and deletes by each for the stream to capture. The model's
``audit`` table is changed too and tracked by none of them (suite ``db2cdc_keys``,
checked ``--untracked audit``).

NO TRIGGER IS INVOLVED: registering a stream publisher STARTS it. The worker comes up
seconds after ``create-project`` and runs until the function is disabled or deleted, so
every variant below is live the moment the suite is created (``tdk worker list`` shows
them; they carry no execution plan or transaction). Each variant sits in its own
collection; Db2 needs no per-stream id — a consumer just reads the CD table and tracks
its own offset, so the four coexist on one set of CD tables.

Variants (see the suite's _comment for how to drive them):
- ``db2cdc_in``        : base — ``start_from="tail"`` (each CD table's current
                         watermark), ``columns_format="columns"`` +
                         ``flatten_columns=True`` -> ordinary tabular change rows.
- ``db2cdc_in_head``   : ``start_from="head"`` — replays each CD table from the origin.
                         Registration happens before ``create-data``, so the seed load
                         is still staged and arrives as inserts.
- ``db2cdc_in_struct`` : ``columns_format="struct"`` + ``flatten_columns=False`` — new
                         and old column payloads arrive as nested structs. Db2
                         registrations are created with ``image both``, so old values
                         are present (prefixed ``_``).
- ``db2cdc_in_map``    : ``columns_format="map"`` with the new columns still inlined, so
                         only the old-values payload becomes a map.

Db2 change rows carry the ASN bookkeeping columns (``IBMSNAP_COMMITSEQ`` /
``IBMSNAP_OPERATION`` / the ``IBMSNAP_LOGMARKER`` the system adds) alongside the
captured ones.
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
    "${D0__CD_TABLE_PREFIX}XP_SENTINEL",
]
_OUTPUT = [
    "accounts_changes",
    "ledger_changes",
    "devices_changes",
    "readings_changes",
    "xp_sentinel_changes",
]

# Small thresholds so a handful of `modify-data` changes flush promptly instead of
# sitting in the buffer; poll every second so the loop reacts quickly. `fetch_size`
# caps the server-side fetch when draining a CD table.
_CFG = {
    "tabsdata.cdc.buffer.max_rows": 100,
    "tabsdata.cdc.buffer.max_secs": 5,
    "tabsdata.cdc.trigger.max_rows": 10,
    "tabsdata.cdc.trigger.max_secs": unsafe_seconds(10),
    "tabsdata.cdc.poll.idle_secs": 1,
    "tabsdata.cdc.poll.max_secs": 5,
    "tabsdata.cdc.fetch_size": 500,
}


_Out = tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]


# `concat` drops None entries and returns None for an empty/None list, so it doubles as
# the "this flush carried nothing for this slot" guard. Vertical (strict) on purpose: a
# mid-stream schema change should surface here rather than be absorbed silently.
@stream_publisher(
    source=Db2CdcStreamSrc(tables=_TABLES, start_from="tail", src_cfg=_CFG),
    flush_interval_mins=1,
    output_tables=_OUTPUT,
)
def db2cdc_in(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> _Out:
    return (concat(accounts), concat(ledger), concat(devices), concat(readings), concat(xp_sentinel))


@stream_publisher(
    source=Db2CdcStreamSrc(tables=_TABLES, start_from="head", src_cfg=_CFG),
    flush_interval_mins=1,
    output_tables=_OUTPUT,
)
def db2cdc_in_head(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> _Out:
    # Each CD table from its origin -> the create-data seed arrives as inserts.
    return (concat(accounts), concat(ledger), concat(devices), concat(readings), concat(xp_sentinel))


@stream_publisher(
    source=Db2CdcStreamSrc(
        tables=_TABLES,
        start_from="tail",
        columns_format="struct",
        flatten_columns=False,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=_OUTPUT,
)
def db2cdc_in_struct(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> _Out:
    # Not flattened: the row's new/old values stay nested under struct columns.
    return (concat(accounts), concat(ledger), concat(devices), concat(readings), concat(xp_sentinel))


@stream_publisher(
    source=Db2CdcStreamSrc(
        tables=_TABLES,
        start_from="tail",
        columns_format="map",
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=_OUTPUT,
)
def db2cdc_in_map(
    accounts: TableFramesSpec,
    ledger: TableFramesSpec,
    devices: TableFramesSpec,
    readings: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> _Out:
    # flatten_columns defaults to True, so the format only shapes the OLD values.
    return (concat(accounts), concat(ledger), concat(devices), concat(readings), concat(xp_sentinel))
