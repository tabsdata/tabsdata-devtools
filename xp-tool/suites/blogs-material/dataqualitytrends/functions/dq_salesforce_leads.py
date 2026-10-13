#
# Copyright 2026 Tabsdata Inc.
#

"""dq_salesforce_leads -- a publisher of a Salesforce *Lead Lifetime* report and a
transformer over it, with data quality whose summaries show which issues improve,
which hold steady and which come and go, and how the pipeline looks run by run.

The report stands in a ``DataGenSrc``: 1000 leads of ``sf_leads_plan``, 100 a
trigger (``chunk_size``), as ten weekly runs of the report would land. Against a
real org the source is the report itself, its columns named the same way --
``dq_salesforce_leads_report`` is this publisher so::

    source=SalesforceReportSrc(reports=["Lead Lifetime Report"], find_report_by="name")

Two kinds of data quality, one per function:

- ingest, on the publisher's ``leads``: is the report clean? Ten boolean
  classifiers -- the issues a sales-ops team chases -- and ``Summary`` with its
  trend, folding them run by run;
- business, on the transformer's ``leads_pipeline`` -- in a collection of its own,
  ``sf_pipeline``, since ``sf_leads`` is a source collection and takes no
  transformer: what does the pipeline look like? Two categorizers -- how long
  open leads have sat untouched, and the rating distribution -- over two columns
  the transformer adds, since a ``ScaleCategorizer`` bins numbers:
  ``OPEN_DAYS`` (an open lead's days in its status, null for the rest)
  and ``RATINGS`` (Cold 1, Warm 2, Hot 3, no rating 0).

Everything the data quality checks is spelled out here; ``sf_leads_plan`` holds
the same values, to make the data and to check the summaries.
"""

from __future__ import annotations

import polars as pl
import tabsdatak.tableframe.datatypes as td_types
from tabsdatak.api import TableFrameSpec, publisher, transformer
from tabsdatak.conn.dev import Data, DataGenSrc
from tabsdatak.dataquality import (
    DataQuality,
    HasLength,
    IdentityScale,
    IsBetween,
    IsIn,
    IsNotIn,
    IsNotNull,
    IsPositive,
    LinearScale,
    Matches,
    ScaleCategorizer,
    Summary,
    Trends,
)
from tabsdatak.tableframe.functions import col, concat, lit

try:
    from . import sf_leads_plan as plan
except ImportError:
    import sf_leads_plan as plan

_SCHEMA = {
    "EMPLOYEES": pl.Int64,
    "ANNUAL_REVENUE": pl.Float64,
    "DAYS_IN_STATUS": pl.Int64,
    "CREATED_DATE": pl.Date,
    "LAST_UPDATE": pl.Date,
    "CONVERTED_DATE": pl.Date,
    "OPPORTUNITY_AMOUNT": pl.Float64,
    "CLOSE_DATE": pl.Date,
}


def report() -> pl.DataFrame:
    """The ten runs of the report, oldest first."""
    found = [r for t in range(plan.TRIGGERS) for r in plan.rows(t)]
    schema = {c: _SCHEMA.get(c, pl.String) for c in plan.COLUMNS}
    return pl.DataFrame(found, schema=schema, orient="row")


# name@domain.tld
EMAIL_REGEX = r"^[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}$"
# a country code, then two to four groups of digits: +44 20 7946 0958
PHONE_REGEX = r"^\+[1-9][0-9]{0,2}( [0-9]{2,4}){2,4}$"
# the lead status picklist
VALID_STATUS = {"Open - Not Contacted", "Working - Contacted", "Closed - Converted", "Closed - Not Converted"}
# what stands in for a company nobody gave: web-to-lead fills in "[not provided]"
MISSING_COMPANY_NAME = {"[not provided]", "N/A", "Unknown", "-", "none"}


@publisher(
    source=DataGenSrc(data=[Data(report(), chunk_size=100)]),
    output_tables=["leads"],
    on_tables=[
        # ingest data quality: is the report clean?
        DataQuality(
            table="leads",
            classifiers=[
                IsNotNull([("EMAIL", "email_present")]),  # checking email is present
                Matches([("EMAIL", "email_valid")], pattern=EMAIL_REGEX),  # checking email is valid
                IsNotNull([("LEAD_SOURCE", "lead_source_present")]),  # checking the lead's source is known
                IsNotIn([("COMPANY", "company_provided")], values=MISSING_COMPANY_NAME),  # checking company is not a placeholder
                IsIn([("RATING", "rating_valid")], values={"Hot", "Warm", "Cold"}),  # checking rating is on its picklist
                IsIn([("STATUS", "status_valid")], values=VALID_STATUS),  # checking status is on its picklist
                IsBetween([("EMPLOYEES", "employees_in_range")], min_val=1, max_val=10_000),  # employees between 1 and 10000
                Matches([("PHONE", "phone_valid")], pattern=PHONE_REGEX),  # checking phone has a country code
                HasLength([("LAST_NAME", "last_name_valid")], min_len=2, max_len=80),  # last name 2 to 80 characters
                IsPositive([("ANNUAL_REVENUE", "revenue_positive")]),  # annual revenue above zero
            ],
            operators=[Summary(trends=Trends())],  # the summary, and its trend run by run
        )
    ],
)
def leads_report(leads: TableFrameSpec) -> TableFrameSpec:
    # After the tenth run the source is spent and the slot None.
    return leads


@transformer(
    input_tables=["sf_leads/leads"],
    output_tables=["leads_pipeline"],
    on_tables=[
        DataQuality(
            table="leads_pipeline",
            classifiers=[
                # histogram on leads not changing status: days an open lead has sat in
                # it, 30-day buckets over a year
                ScaleCategorizer(
                    [("OPEN_DAYS", "open_days_bucket")],
                    scale=LinearScale(0, 360, bins=12),
                ),
                # rating distribution: no rating (0), Cold (1), Warm (2) and Hot (3)
                ScaleCategorizer(
                    [("RATINGS", "rating_bucket")],
                    scale=IdentityScale(0, 3, use_bin_zero=True),
                ),
            ],
            operators=[Summary()],
        )
    ],
)
def leads_pipeline(leads: TableFrameSpec) -> TableFrameSpec:
    if leads is None:
        return None
    # Open leads keep their days in status; every other lead has none.
    opened = leads.filter(col("STATUS") == "Open - Not Contacted").with_columns(
        col("DAYS_IN_STATUS").alias("OPEN_DAYS")
    )
    others = leads.filter(col("STATUS").ne_missing("Open - Not Contacted")).with_columns(
        lit(None).cast(td_types.Int64).alias("OPEN_DAYS")
    )
    # Cold 1, Warm 2, Hot 3; anything else is no rating, 0.
    code = col("RATING").str.replace_many({"Cold": "1", "Warm": "2", "Hot": "3"})
    code = code.cast(td_types.Int8, strict=False).fill_null(0)
    return concat([opened, others]).with_columns(code.alias("RATINGS"))
