#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce REPORT source: reading a report BY ID.

REPORTS vs SOQL. `SalesforceReportSrc` downloads the result of an Analytics
REPORT — the thing a business user built in the UI, with its own columns,
groupings and saved filters. Use it when the DEFINITION of "the data" lives with
that user rather than in your code; use `SalesforceSrc` (SOQL) when you want to
state the query yourself.

TABULAR REPORTS ONLY. Summary and matrix reports are grouped rather than flat and
are not supported.

Unlike `queries`, `reports` takes MANY entries — one output slot and one output
table per report (see `read_many.py`). That is the one place the report source is
more capable than the SOQL one.

IDENTIFYING A REPORT: an entry may be a report ID (15 or 18 alphanumeric chars)
or a report NAME. `find_report_by` breaks the tie when a string could be read as
either — `"id"` forces id lookup, `"name"` forces name lookup, unset auto-detects.
Whichever you use, the emitted `@td.salesforce.report_id` metadata column records
the RESOLVED id, so a name-driven read is still traceable to the exact report it
hit.

WHY THIS SUITE IS REGISTERED BUT NOT TRIGGERED
    A report is ORG CONTENT: it has to exist before it can be read, and the
    `salesforce` model does not create any. So the suite registers these
    publishers — enough to validate the shapes and have them ready — and triggers
    NONE of them, which keeps a run green on an org with no reports.

    Create a Tabular report on Account, put its id or name in the constant below,
    and fire one by hand:

        tdk fn trigger --proj <project> --coll reports --name read_by_id
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc


@publisher(
    source=SalesforceReportSrc(
        # Replace with a Tabular report id from your org.
        reports=["00O000000000000AAA"],
        find_report_by="id",
    ),
    output_tables=["accounts_report"],
)
def read_by_id(accounts: TableFrameSpec) -> TableFrameSpec:
    # One report -> one slot -> one table. SINGLE mode, like every SQL-shaped
    # source: the slot is a frame, not a list.
    return accounts
