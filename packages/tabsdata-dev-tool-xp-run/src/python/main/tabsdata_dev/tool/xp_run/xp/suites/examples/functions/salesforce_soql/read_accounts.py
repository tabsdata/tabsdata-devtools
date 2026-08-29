#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce SOQL source: a full read of one object.

ONE QUERY PER PUBLISHER. `SalesforceSrc.queries` is a LIST, but today it accepts
EXACTLY ONE entry — the list shape is there so multi-query can arrive later
without a field rename. So "read several objects" means SEVERAL PUBLISHERS, one
per object (`read_opportunities.py` is the second). They are independent
functions with independent triggers and independent failure, which is usually
what you want against an API with per-object permissions and per-object limits.

Like every SQL-shaped source this is SINGLE mode: the slot is one frame, not a
list.

THERE IS NO `SELECT *` IN SOQL, which is why every query in this suite lists its
fields. That is a feature at this end: a field added in Salesforce cannot silently
widen your table.

WHAT THE ORG HOLDS
    The `salesforce` model loads 75 Accounts with 1–4 Opportunities each —
    `Name`, `Industry`, `Type`, `AnnualRevenue`, `NumberOfEmployees`, `Billing*`
    on Account; `AccountId`, `Name`, `StageName`, `CloseDate`, `Amount` on
    Opportunity. Both are standard objects, so `create-model` installs nothing.

    NOTE `create-data` on a salesforce domain is DESTRUCTIVE: it deletes every
    Account and Opportunity in the org before bulk-loading. Point it at a scratch
    org.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceSrc


@publisher(
    source=SalesforceSrc(
        queries=[
            "SELECT Id, Name, Industry, Type, AnnualRevenue, NumberOfEmployees, "
            "BillingCity, BillingState, LastModifiedDate FROM Account"
        ],
    ),
    output_tables=["accounts"],
)
def read_accounts(accounts: TableFrameSpec) -> TableFrameSpec:
    return accounts
