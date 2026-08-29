#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce SOQL source: `$lastModified`, A STATIC FLOOR.

Put the literal token `$lastModified` anywhere in the SOQL and the source
substitutes `initial_last_modified`, formatted the way Salesforce expects.

TWO RULES, and the second is the one that surprises people:

  * A query mentioning `$lastModified` with NO `initial_last_modified` set is
    REJECTED before it runs.
  * THE CUTOFF DOES NOT ADVANCE between runs. Unlike a file source — which
    advances `initial_last_modified` for you — and unlike a SQL source, where
    `ctx` advances the bind, the Salesforce cutoff is FIXED at registration.

So this is not a cursor. Treat it as "never look further back than this": a cheap
bound on how much history the org has to scan, which keeps a large object's query
from getting slower every month.

For an actually-incremental read, see `read_new_opportunities.py`, which adds the
moving half in the function body.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceSrc


@publisher(
    source=SalesforceSrc(
        queries=[
            "SELECT Id, Name, Industry, LastModifiedDate FROM Account "
            "WHERE LastModifiedDate > $lastModified ORDER BY LastModifiedDate"
        ],
        # Far enough back to take everything the model loads; near enough to keep
        # the org from scanning history. The same rows come back on every run —
        # the cutoff is STATIC.
        initial_last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["accounts_since_floor"],
)
def read_recent_accounts(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
