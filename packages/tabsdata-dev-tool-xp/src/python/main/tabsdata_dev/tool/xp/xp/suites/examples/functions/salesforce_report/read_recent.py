#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce REPORT source: INCREMENTAL, by last-modified column.

`last_modified_column` names the report column carrying the modification time and
`initial_last_modified` is the cutoff it is compared against.

THE TWO FIELDS ARE ALL-OR-NOTHING: setting one without the other fails validation
at decoration time, before anything runs. That is a deliberate guard — a cutoff
with no column to apply it to would silently do nothing.

As with SOQL, the cutoff is a STATIC FLOOR, not an advancing cursor. See
`salesforce_soql/read_new_opportunities.py` for how to add the moving half with
`ctx`; the same two-layer pattern applies here, with the report's own
last-modified column playing the part of `LastModifiedDate`.

The column name is the report's, in whatever `column_name_strategy` you are
using — so switching that strategy means changing this too.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc


@publisher(
    source=SalesforceReportSrc(
        reports=["Accounts by Industry"],
        find_report_by="name",
        last_modified_column="LAST_UPDATE",
        initial_last_modified=datetime(2020, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["accounts_report_recent"],
)
def read_recent(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
