#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — PostgreSQL CDC: REPLAY from the earliest position the source retains.

    `start_from="head"` —
    the oldest WAL the slot still retains. NOTE logical decoding cannot reach
    back past SLOT CREATION, so on Postgres this does NOT replay a pre-existing
    table — unlike MySQL and Db2. It differs from `"tail"` only for changes
    made while the consumer was away.

    `LsnPosition(lsn=N)` resumes at an exact WAL LSN — the shape the runner
    itself persists (`{"lsn": N}`), so it is how you rewind a stream to a
    known point by hand.

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
  keys; the files are staged as one batch when a `batch_*` threshold of the
  decorator fires, and never sooner than `batch_min_secs` (60 by default) after
  the previous batch.

WHAT `tables` MEANS HERE
    Unqualified names resolve against the connection's `current_schema`
    (`public` for these domains), so the same function works whatever database
    the domain was given.

THE CURSOR: REPLICATION SLOT
    Postgres logical decoding needs a SLOT: a persistent WAL cursor the server
    will not garbage-collect until the consumer confirms it.
    `replication_slot_behavior="reuse"` (the default) requires the slot to
    exist; `"create"` creates it and no-ops if it does.

    A slot admits ONE active consumer, so every concurrent stream needs its
    OWN slot name — and its own collection, since these four run at once.

    OPERATIONAL WARNING: an abandoned slot PINS WAL FOREVER and will fill the
    server's disk. If you stop consuming, drop it:
        SELECT pg_drop_replication_slot('ex_cdc_tabular');

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
    The `postgrescdc` system sets `REPLICA IDENTITY FULL` on every model table,
    so UPDATE and DELETE rows carry complete before-images. WITHOUT it Postgres
    sends only the key columns and the old side is mostly null.

WHEN A BATCH CLOSES: `src_cfg` and the batch thresholds
    `tabsdata.cdc.buffer.max_rows` / `.max_bytes` / `.max_secs` bound the
    in-memory buffer; the decorator's `batch_max_rows` / `batch_max_bytes` /
    `batch_max_secs` decide when a batch is emitted; `tabsdata.cdc.poll.max_secs` is
    how long one poll waits for changes and `tabsdata.cdc.poll.idle_secs` how
    long the loop rests after a poll that found none. The small values below
    make a demo responsive; production wants larger batches and fewer, bigger
    files.

DRIVING IT
    tdd xp one-shot --suite examples/postgrescdc_stream --keep      # the streams start
    tdd domain modify-data --domain <XP_ID>_postgrescdc_employees_xs \\
        --entity employees --ops Mix --sets 5

    `--ops` takes ONE of `Insert` / `Update` / `Delete` / `Mix` — not a list.
    `Mix` is what gives the stream all three operations in one go, which is the
    point when what you are looking at is `@td.cdc.meta.op`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.postgres import PostgresCdcStreamSrc
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source=PostgresCdcStreamSrc(
        tables=["employees", "departments"],
        replication_slot="ex_cdc_replay",
        replication_slot_behavior="create",
        start_from="head",
        columns_format="columns",
        flatten_columns=True,
        src_cfg={
            "tabsdata.cdc.buffer.max_rows": 100,
            "tabsdata.cdc.buffer.max_secs": 5,
            "tabsdata.cdc.poll.idle_secs": 1,
            "tabsdata.cdc.poll.max_secs": 5,
        },
    ),
    batch_max_secs=60,
    batch_max_rows=10,
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
