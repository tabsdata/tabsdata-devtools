#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 CDC: REPLAY from the earliest position the source retains.

    `start_from="head"` —
    replays each tracked CD table from its origin — so, like MySQL and unlike
    Postgres, it can replay a load that happened before the stream started, for
    as long as the CD table still holds it.

    `CommitSeqPosition(...)` resumes at a global commit sequence,
    `TableCommitSeqPosition(...)` at a per-table one, and
    `TimestampPosition(ts=...)` at a wall clock.

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
    `tables` NAMES THE CD TABLES, NOT THE SOURCE TABLES. Db2 SQL Replication
    captures changes into shadow change-data tables that the ASN capture
    program (`asncap`) populates in the background, so what the stream reads is
    the CD table of `EMPLOYEES`, not `EMPLOYEES`; the ingester resolves the
    source back through `ASN.IBMSNAP_REGISTER`. The CD tables are the domain's
    own -- `ASN.TD_<tag of its schema>__<TABLE>` -- and it records the prefix
    as `CD_TABLE_PREFIX`, which xp puts in for `${D0__CD_TABLE_PREFIX}` when it
    registers the function. Db2 also folds unquoted identifiers to uppercase,
    which is why the names are written that way.

THE CURSOR: CAPTURE-TABLE WATERMARK
    There is no slot and no replica id — each tracked CD table has its own
    watermark, and the stream drains them. What Db2 has instead is a
    REGISTRATION per captured table, and that is where the operational
    weight of this connector sits.

    EACH DOMAIN HAS ITS OWN CD TABLES, named after its schema, so any number
    of db2cdc domains carrying the same model share a system -- this suite
    and `container-connectors/db2cdc` can be up together.

    A DESTROY CLEANS UP -- `Db2Cdc.destroy_domain` deregisters every
    table it finds in `ASN.IBMSNAP_REGISTER` under the domain's schema before
    dropping that schema (CAPSTOP, delete the REGISTER and PRUNCNTL rows,
    drop the `LM_TD_<tag>__<T>` trigger, drop the CD table, clear DATA
    CAPTURE). That is why a destroy takes minutes rather than a second. A
    domain torn down some other way leaves its registrations behind, holding
    names only a domain of the same schema would want.

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
    The CD tables carry the before-image when the registration was created with
    full-row capture, which the `db2cdc` system does.

WHEN A BATCH CLOSES: `src_cfg`
    `tabsdata.cdc.buffer.max_rows` / `.max_bytes` / `.max_secs` bound the
    in-memory buffer; `tabsdata.cdc.trigger.max_rows` / `.max_bytes` /
    `.max_secs` decide when a batch is emitted; `tabsdata.cdc.poll_interval_
    seconds` is how often the loop looks. The small values below make a demo
    responsive; production wants larger batches and fewer, bigger files.

DRIVING IT
    tdx-xp oneshot --suite examples/db2cdc_stream --keep      # the streams start
    tdx-domain modify-data --domain <instance>_db2cdc_employees_xs \\
        --entity employees --ops Mix --sets 5

    `--ops` takes ONE of `Insert` / `Update` / `Delete` / `Mix` — not a list.
    `Mix` is what gives the stream all three operations in one go, which is the
    point when what you are looking at is `@td.cdc.meta.op`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.db2 import Db2CdcStreamSrc
from tabsdatak.tableframe.functions import concat


@stream_publisher(
    source=Db2CdcStreamSrc(
        tables=["${D0__CD_TABLE_PREFIX}EMPLOYEES", "${D0__CD_TABLE_PREFIX}DEPARTMENTS"],
        start_from="head",
        columns_format="columns",
        flatten_columns=True,
        src_cfg={
            "tabsdata.cdc.buffer.max_rows": 100,
            "tabsdata.cdc.buffer.max_secs": 5,
            "tabsdata.cdc.trigger.max_rows": 10,
            "tabsdata.cdc.trigger.max_secs": 60,
            "tabsdata.cdc.poll_interval_seconds": 1,
            "db2.cdc.blocking_timeout_seconds": 5,
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
