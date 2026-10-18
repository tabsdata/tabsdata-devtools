#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce SOQL source: A GENUINELY INCREMENTAL READ, in two layers.

Because `$lastModified` is a static floor (see `read_recent_accounts.py`), an
incremental Salesforce read has to be built out of two halves:

  1. A CHEAP FLOOR in the SOQL — `$lastModified` — so the API is not asked for
     the whole history on every run. This half is fixed.
  2. A MOVING WATERMARK held in `ctx`, applied in the function body, so each run
     publishes only what is new since the previous one. This half advances.

That second half is the same idea as the SQL sources' `initial_values` cursor,
just applied after the fetch instead of inside the query — the cost being that
the org still returns everything above the floor, and this function throws most
of it away. Worth it when the floor is tight; not a substitute for a real cursor
when the object is huge.

`LastModifiedDate` arrives as an ISO-8601 STRING, and ISO-8601 in a fixed zone
sorts lexicographically — so a plain `>` comparison is a correct time comparison
here, and `max_for` picks the true maximum.

THE NO-RESULTS RULE APPLIES UNCHANGED: when everything returned was already
published, leave the watermark where it is and return `None`. Resetting it in
that branch re-ingests the org's history the next time something changes.

`ctx` scratch keys are a flat namespace shared with the connectors, which reserve
`file-lastmod.*` for their own bookkeeping — so pick a plain name, as here.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, TransactionCtx, publisher
from tabsdatak.conn.salesforce import SalesforceSrc
from tabsdatak.tableframe.functions import col, lit


@publisher(
    source=SalesforceSrc(
        queries=[
            "SELECT Id, AccountId, Name, StageName, Amount, LastModifiedDate "
            "FROM Opportunity WHERE LastModifiedDate > $lastModified "
            "ORDER BY LastModifiedDate"
        ],
        initial_last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["opportunities_new"],
)
def read_new_opportunities(opps: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if opps is None:
        return None
    seen = ctx.get_attr("last_modified_seen")
    if seen is not None:
        opps = opps.filter(col("LastModifiedDate") > lit(seen))
    top = opps.max_for("LastModifiedDate")
    if top is None or top["LastModifiedDate"] is None:
        # Everything the org returned was already published: no new version, and
        # — as always — leave the watermark alone rather than resetting it.
        return None
    ctx.set_attr("last_modified_seen", str(top["LastModifiedDate"]))
    return opps
