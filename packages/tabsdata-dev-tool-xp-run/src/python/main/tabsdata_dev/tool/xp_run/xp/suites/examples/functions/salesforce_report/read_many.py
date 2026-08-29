#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce REPORT source: SEVERAL REPORTS in one publisher.

`reports` takes many entries: one output slot and one output table each, in
order — positional, exactly like a SQL source's `queries`.

This is the one shape the report source has and the SOQL source does not. Use it
when the reports belong together (a set of dashboards refreshed as a unit); use
separate publishers when they do not, so one failing report does not hold up the
others.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc


@publisher(
    source=SalesforceReportSrc(
        reports=["Accounts by Industry", "Open Opportunities"],
        find_report_by="name",
    ),
    output_tables=["accounts_report_multi", "opportunities_report_multi"],
)
def read_many(
    accounts: TableFrameSpec,
    opportunities: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (accounts, opportunities)
