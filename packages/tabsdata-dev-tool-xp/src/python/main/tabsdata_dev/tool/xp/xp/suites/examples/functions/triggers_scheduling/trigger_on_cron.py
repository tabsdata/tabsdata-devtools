#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — WHEN a function runs: `trigger_by=CronTrigger(...)`, a schedule.

Every other example in this set answers "what does this connector do". This one
answers the other half — WHAT MAKES THE FUNCTION RUN AT ALL — which the suite
descriptors have been quietly doing on your behalf via their `triggers` list
(`tdk fn trigger`, fired by hand). A function that carries `trigger_by` needs no
such help: the RUNTIME fires it.

THE FOUR ANSWERS

    (nothing)              fired by hand, or reactively because a table it reads
                           with `@NEW` got a new version. The default, and what
                           every other examples suite uses.
    CronTrigger(mask=...)  on a clock. PUBLISHERS ONLY — a publisher has no
                           upstream table to react to, so a schedule is the only
                           thing that can start it.
    TablesTrigger(tables)  when one of a NAMED set of upstream tables produces a
                           batch (see trigger_on_named_tables.py).
    AllTablesTrigger()     when ANY table the function reads produces a batch
                           (see trigger_on_any_table.py).

THE MASK is a five-field UNIX cron expression in UTC — minute granularity, no
seconds field — or one of the descriptors `@yearly`, `@annually`, `@monthly`,
`@weekly`, `@daily`, `@midnight`, `@hourly`. These are Kubernetes CronJob
schedules, so anything valid there is valid here.

PAIRED WITH A CHUNKED SOURCE, which is what makes a schedule observable:
`Data(df, chunk_size=N)` emits the NEXT N rows per RUN, advancing an offset kept
in the plugin's per-flow state. So this table grows by 5 rows a minute and walks
the 20-row frame in four ticks; on the fifth the slot arrives as `None` and
nothing is published — the run still happens, it just emits no batch.

That cursor advances PER RUN, whoever started it. A `trigger_by` function can
still be fired by hand, and doing so consumes a chunk exactly as a tick would.

WATCHING IT WORK: `oneshot` without `--keep` tears the project down as soon as
the monitor returns, which is usually BEFORE the first tick. Use `--keep` and
leave it running:

    tdx-xp oneshot --suite examples/triggers_scheduling --keep
    td -P <project> table versions --coll scheduled --name batches   # grows each minute
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import CronTrigger, TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(
                pl.DataFrame({
                    "id": list(range(1, 21)),
                    "name": [f"row-{i:02d}" for i in range(1, 21)],
                }),
                chunk_size=5,
            )
        ]
    ),
    output_tables=["batches"],
    trigger_by=CronTrigger(mask="* * * * *"),
)
def trigger_on_cron(batch: TableFrameSpec) -> TableFrameSpec:
    # The next 5 rows, once a minute, then None once the 20 are spent.
    return batch
