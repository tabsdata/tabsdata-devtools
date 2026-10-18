#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Db2 source: THE INCREMENTAL READ, one page per run.

THE THREE PIECES
    1. BIND the watermark into the SQL as `:name` — a real, typed statement
       parameter, never string interpolation. No injection, no quoting, no
       dialect-specific literal formatting.
    2. SEED it with `initial_values`. This is the FIRST-RUN value ONLY: on every
       run the plugin reads `ctx.get_attr(name)` first and falls back to the seed
       when the store has no entry — so editing the seed later does NOT rewind a
       function that has already run.
    3. ADVANCE it from the batch you just read, with `ctx.set_attr`. The value
       persists on the flow's scratch state across transactions.

    A function that wants `ctx` just declares a parameter named `ctx`, after the
    table slots. (A `@stream_publisher` may NOT declare one.)

    `FETCH FIRST 10 ROWS ONLY` is this dialect's row limit.

    Db2 folds UNQUOTED identifiers to UPPERCASE, exactly as Oracle does, so
    the frames come back with `ID` / `NAME` / `COUNTRY_CODE` and anything
    naming a column by string has to match. Row limiting is
    `FETCH FIRST n ROWS ONLY`.
    So `max_for` below must be given `"ID"`, not `"id"` — and a
    watermark reader copy-pasted from a lowercase dialect fails at RUN time,
    with a column-not-found, rather than at registration.

GETTING THE NEW WATERMARK: `max_for()` returns the requested columns OF THE
TOP-RANKING ROW as a `{column: value}` dict, or `None` when the frame is empty.
Read it off THE DATA YOU ACTUALLY PUBLISHED, never off a separate
`SELECT max(...)`: a second query could see rows this batch did not, and those
rows would be skipped forever.

`ORDER BY` is not optional. Without it "the next 10 rows" is undefined and a
paging read silently loses data.

RUN THE PROJECT SEVERAL TIMES and watch the table grow by one page each time.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TransactionCtx, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(
        queries=[
            "SELECT * FROM city WHERE id > :wm "
            "ORDER BY id FETCH FIRST 10 ROWS ONLY"
        ],
        initial_values={"wm": 0},
    ),
    output_tables=["city_page"],
)
def read_watermark_by_id(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is None:
        return None
    top = city.max_for("ID")
    if top is not None and top["ID"] is not None:
        ctx.set_attr("wm", int(top["ID"]))
    return city
