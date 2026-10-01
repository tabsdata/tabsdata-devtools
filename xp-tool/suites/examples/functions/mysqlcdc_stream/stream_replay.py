#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MySQL CDC: REPLAY from the earliest position the source retains.

    `start_from="head"` —
    the oldest retained binlog event — and the binlog is retained server-wide
    (3 days on this container), so `"head"` GENUINELY REPLAYS history,
    including the `create-data` seed load, which arrives as a wave of INSERTs.
    That is a full backfill and an ongoing stream from ONE function. It also
    scans other databases' traffic on the same server and filters it out, so
    expect a slow first pass.

    `BinlogPosition(file=..., pos=4)` resumes at an exact file + byte offset
    (`pos=4` skips the binlog magic bytes, i.e. that file from its
    beginning); `GtidPosition(gtid="uuid:N")` resumes after a Global
    Transaction ID; `TimestampPosition(ts=...)` at the first event at or
    after a wall clock. `SHOW BINARY LOGS` / `SHOW MASTER STATUS` tell you
    what to put there. All of them are SEEDS, used only until the stream
    persists its own offset.

A CDC SOURCE IS NOT A PUBLISHER. `@stream_publisher`, and the differences are
all operational:

  * NO TRIGGER. Registering a stream publisher STARTS it. The worker comes up
    seconds after `create-project` and runs until the function is disabled or
    deleted — which is why this suite's `triggers` list is empty. `tdk worker
    list` shows them; they carry no execution plan.
  * ONE SLOT PER TRACKED TABLE (`cardinality = len(tables)`), and each slot is an
    ARRAY of the frames that flush carried — like a file source, not like a SQL
    source. Fold with `concat`.
  * NO `ctx` PARAMETER. A stream publisher runs in the runtime's stream loop, not
    per transaction; declaring `ctx` is an error.

  Changes are buffered and written to parquet files per the `tabsdata.cdc.buffer.*`
  keys; the files are staged as one batch when a `tabsdata.cdc.trigger.*` threshold
  fires (`src_cfg`) or when `flush_interval_mins` is reached, and never sooner than
  60 seconds after the previous batch.

WHAT `tables` MEANS HERE
    Unqualified names resolve against the connection's default database.

THE CURSOR: SERVER_ID
    MySQL has NO slot to create or drop. Every consumer registers as a REPLICA,
    and MySQL admits a single replica per `server_id`: a second stream
    attaching with the same id disconnects the first with
    `(1236, "A replica with the same server_uuid/server_id ...")`.

    `server_id` lives on the CONNECTION, not on the source — so each variant
    here gets its own connection template (`connections/mysql_cdc_612.yaml`
    through `_615.yaml`, a block kept clear of the 51x ids the connectors
    capability suite uses) and therefore its own collection.

    The upside of having no slot: nothing pins the binlog when you walk away.
    A stopped MySQL stream leaks nothing; a stopped Postgres one holds WAL.

WHAT EVERY EMITTED ROW CARRIES
    Change METADATA under `@td.cdc.meta.*`:
        op  'i' | 'u' | 'd'        tx   transaction id     ts  commit time
        sq  sequence in the tx     ord  global ordering    sch source schema
        fmt / flat / seg           (the config the row was produced under)

    and the VALUES, laid out by `columns_format` and `flatten_columns` TOGETHER:

        flatten_columns=True (default)   the NEW values are inlined as ordinary
                                         top-level columns, so the row reads like
                                         a normal table row and `columns_format`
                                         then only shapes the OLD values.
        columns_format="columns"         one column per field per side:
                                         `@td.cdc.data.col.new.<field>` /
                                         `@td.cdc.data.col.old.<field>`
        columns_format="struct"          one nested struct per side:
                                         `@td.cdc.data.row.new` / `.row.old`
        columns_format="map"             one map per side:
                                         `@td.cdc.data.map.new` / `.map.old`

    RULE OF THUMB: `columns` + flattened for anything that lands in a table and
    gets queried; `struct` / `map` when the tracked table's schema may CHANGE
    mid-stream and you would rather carry the payload opaquely than have the
    frame's columns shift underneath you.

    BEFORE-IMAGES:
    MySQL's row-based binlog carries the full before-image on UPDATE and DELETE
    with no extra configuration — there is no `REPLICA IDENTITY` to set.

WHEN A BATCH CLOSES: `src_cfg`
    `tabsdata.cdc.buffer.max_rows` / `.max_bytes` / `.max_secs` bound the
    in-memory buffer; `tabsdata.cdc.trigger.max_rows` / `.max_bytes` /
    `.max_secs` decide when a batch is emitted; `tabsdata.cdc.poll_interval_
    seconds` is how often the loop looks. The small values below make a demo
    responsive; production wants larger batches and fewer, bigger files.

DRIVING IT
    tdd xp one-shot --suite examples/mysqlcdc_stream --keep      # the streams start
    tdd domain modify-data --domain <XP_ID>_mysqlcdc_employees_xs \\
        --entity employees --ops Mix --sets 5

    `--ops` takes ONE of `Insert` / `Update` / `Delete` / `Mix` — not a list.
    `Mix` is what gives the stream all three operations in one go, which is the
    point when what you are looking at is `@td.cdc.meta.op`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=["employees", "departments"],
        start_from="head",
        columns_format="columns",
        flatten_columns=True,
        src_cfg={
            "tabsdata.cdc.buffer.max_rows": 100,
            "tabsdata.cdc.buffer.max_secs": 5,
            "tabsdata.cdc.trigger.max_rows": 10,
            "tabsdata.cdc.trigger.max_secs": 60,
            "tabsdata.cdc.poll_interval_seconds": 1,
            "mysql.cdc.blocking_timeout_seconds": 5,
        },
    ),
    flush_interval_mins=1,
    output_tables=["emp_changes", "dept_changes"],
)
def stream_replay(
    employees: TableFramesSpec,
    departments: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # One slot per tracked table, each an ARRAY of the frames this flush carried.
    # `concat` drops Nones and returns None for an empty list, so it doubles as
    # the "this flush carried nothing for this slot" guard. Vertical (the strict
    # default) on purpose: a mid-stream schema change should surface here rather
    # than be absorbed silently.
    return (concat(employees), concat(departments))
