#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — MySQL source: THE NO-RESULTS RULE, which is the one that bites.

This query can never return a row, so the empty path runs on EVERY run rather
than only once the table is drained.

WHEN THE BATCH IS EMPTY:

  * Do NOT call `ctx.set_attr`. Leave the watermark where it is. It STALLS at
    the last value, which is correct — the next run re-runs the same `WHERE` and
    picks up whatever arrived since.
  * Do NOT write a fallback like `ctx.set_attr("wm", 0)` in the empty branch.
    That REWINDS the cursor and re-ingests everything, forever, every time the
    source goes quiet. This is the single most common incremental bug, and it
    only shows up in production, where sources go quiet.
  * Return `None`, so no version of the table is published.

`max_for` returning `None`, and the column being `None` inside the returned dict,
are two different empties — the guard below checks both.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TransactionCtx, publisher
from tabsdatak.conn.mysql import MySQLSrc


@publisher(
    source=MySQLSrc(
        queries=["SELECT * FROM city WHERE id > :wm AND 1 = 0"],
        initial_values={"wm": 0},
    ),
    output_tables=["city_never"],
)
def read_always_empty(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("id")
    if top is not None and top["id"] is not None:
        ctx.set_attr("wm", int(top["id"]))
    return city
