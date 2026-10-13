#
# Copyright 2026 Tabsdata Inc.
#

"""dq_salesforce_leads_report -- ``dq_salesforce_leads.leads_report`` against a real
org: the same publisher and data quality, its source the Salesforce *Lead Lifetime*
report itself rather than a ``DataGenSrc``. No suite registers it; it is the
version to show.

Register it in a ``salesforce_report_in`` collection -- the collection holds the
connection to the org -- and the transformer over ``<collection>/leads`` follows
as it is.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceReportSrc
from tabsdatak.dataquality import (
    DataQuality,
    HasLength,
    IsBetween,
    IsIn,
    IsNotIn,
    IsNotNull,
    IsPositive,
    Matches,
    Summary,
    Trends,
)

# name@domain.tld
EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
# a country code, then two to four groups of digits: +44 20 7946 0958
PHONE_REGEX = r"^\+[1-9][0-9]{0,2}( [0-9]{2,4}){2,4}$"


VALID_STATUS = {"Open - Not Contacted", "Working - Contacted", "Closed - Converted", "Closed - Not Converted"}
MISSING_COMPANY_NAME = {"[not provided]", "N/A", "Unknown", "-", "none"}

@publisher(
    source=SalesforceReportSrc(reports=["Lead Lifetime Report"], find_report_by="name"),
    output_tables=["leads"],
    on_tables=[
        # ingest data quality: is the report clean?
        DataQuality(
            table="leads",
            classifiers=[
                IsNotNull([("EMAIL", "email_present")]),
                Matches([("EMAIL", "email_valid")], pattern=EMAIL_REGEX),
                IsNotNull([("LEAD_SOURCE", "lead_source_present")]),
                IsNotIn([("COMPANY", "company_provided")], values=MISSING_COMPANY_NAME),
                IsIn([("RATING", "rating_valid")], values={"Hot", "Warm", "Cold"}),
                IsIn([("STATUS", "status_valid")], values=VALID_STATUS),
                IsBetween([("EMPLOYEES", "employees_in_range")], min_val=1, max_val=10_000),
                Matches([("PHONE", "phone_valid")], pattern=PHONE_REGEX),
                HasLength([("LAST_NAME", "last_name_valid")], min_len=2, max_len=80),
                IsPositive([("ANNUAL_REVENUE", "revenue_positive")]),
            ],
            operators=[Summary(trends=Trends())],
        )
    ],
)
def leads_report(leads: TableFrameSpec) -> TableFrameSpec:
    return leads
