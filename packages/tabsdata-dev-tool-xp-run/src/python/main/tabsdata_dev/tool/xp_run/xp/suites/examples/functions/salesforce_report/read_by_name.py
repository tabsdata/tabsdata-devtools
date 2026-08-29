#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce REPORT source: BY NAME, and `column_name_strategy`.

`find_report_by="name"` forces name lookup, which is what you want when the
report is maintained by someone who may recreate it (a new report has a new id;
the name is what survives).

`column_name_strategy` decides what the columns are called:

    "columnName"  (the default) API names — `ACCOUNT.NAME`
    "label"       the report's DISPLAY names — `Account Name`

PREFER THE DEFAULT for anything a pipeline consumes. Display labels change
whenever someone edits the report's column headings, and that change arrives as a
silently renamed column rather than as an error — the same class of breakage as a
CSV dialect mismatch. `"label"` is for a one-off extract a human will read.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc


@publisher(
    source=SalesforceReportSrc(
        reports=["Accounts by Industry"],
        find_report_by="name",
        column_name_strategy="label",
    ),
    output_tables=["accounts_report_labelled"],
)
def read_by_name(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
