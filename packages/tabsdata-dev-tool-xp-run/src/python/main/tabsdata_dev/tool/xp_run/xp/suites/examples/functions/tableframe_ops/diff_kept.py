#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: THE INTERSECTION, via a SEMI JOIN.

`how="semi"` keeps the left rows that DO have a match, without bringing the right
side's columns along. It is a FILTER BY MEMBERSHIP in another table — the
TableFrame spelling of `WHERE id IN (SELECT id FROM other)`.

Reach for it whenever the right-hand table is a lookup you want to filter by and
not to read: an allow-list, a set of active ids, the keys that survived a quality
check. An inner join would work and then leave you dropping columns; semi says
what you meant.

It also cannot fan out. An inner join against a right side with duplicate keys
multiplies rows; a semi join returns at most the left rows it started with, which
is often the real reason to choose it.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["src/customers@NEW", "src/customers_previous@HEAD"],
    output_tables=["customers_kept"],
)
def diff_kept(current: TableFrameSpec, previous: TableFrameSpec) -> TableFrameSpec:
    return current.join(previous, on="customer_id", how="semi")
