#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Salesforce SOQL source: a SECOND object means a SECOND publisher.

This is the whole answer to "how do I read more than one object": another
function. `queries` takes one entry, so there is no multi-slot form to reach for.

The trade is worth stating, because it is the opposite of the SQL sources: there,
several queries in one publisher share ONE transactional session and therefore
one consistent snapshot. Here each publisher is its own API session, so Account
and Opportunity are read at different moments and can disagree — an Opportunity
whose Account arrived in the previous run, say. Join defensively downstream
(a left join, not an inner one) rather than assuming referential integrity across
two independent reads.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.salesforce import SalesforceSrc


@publisher(
    source=SalesforceSrc(
        queries=[
            "SELECT Id, AccountId, Name, StageName, CloseDate, Amount, "
            "LastModifiedDate FROM Opportunity"
        ],
    ),
    output_tables=["opportunities"],
)
def read_opportunities(opportunities: TableFrameSpec) -> TableFrameSpec:
    return opportunities
