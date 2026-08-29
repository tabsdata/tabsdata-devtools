#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce REPORT source: SERVER-SIDE FILTERS.

`filter` is a list of `(column, operator, value)` triples that Salesforce applies
BEFORE the download — so they cut TRANSFER, not just rows in the frame. On a
report that returns tens of thousands of rows, that is the difference between a
read that finishes and one that times out.

The operators are the Analytics API's, not SQL's: `equals`, `notEqual`,
`lessThan`, `greaterThan`, `lessOrEqual`, `greaterOrEqual`, `contains`,
`notContain`, `startsWith`, `includes`, `excludes`, `within`, `between`.

`filter_logic` combines them by 1-BASED POSITION — `"(1 OR 2) AND 3"` refers to
the first, second and third entries of `filter`. Without it they are ANDed. Note
the coupling that creates: REORDERING `filter` CHANGES THE MEANING of
`filter_logic`, so edit the two together.

Values are strings even when the column is numeric — `"1000000"`, not `1000000`;
the API takes the report's own formatting.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc


@publisher(
    source=SalesforceReportSrc(
        reports=["Accounts by Industry"],
        find_report_by="name",
        filter=[
            ("ACCOUNT.TYPE", "equals", "Customer - Direct"),
            ("ACCOUNT.INDUSTRY", "equals", "Technology"),
            ("SALES.ANNUAL_REVENUE", "greaterThan", "1000000"),
        ],
        filter_logic="(1 OR 2) AND 3",
    ),
    output_tables=["accounts_report_filtered"],
)
def read_filtered(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
