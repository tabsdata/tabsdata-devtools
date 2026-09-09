#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: an INNER JOIN, and what `@NEW` / `@HEAD` mean.

USE THE TABLEFRAME API, NOT POLARS. A TableFrame carries the framework's system
columns (provenance, versioning) alongside your data, and the TableFrame
operations maintain them. The conversions OUT (`_to_polars_lf`, `_to_polars_df`,
`_to_pandas`, `_to_dict`) are deliberately PRIVATE: each collects the frame
internally, and anything that makes that round trip has lost the bookkeeping.
Test harnesses reach for them to assert on a result; pipeline code should not.

`@NEW` vs `@HEAD` — the two halves of an input reference:

    `src/orders@NEW`      run when THIS table gets a new version
    `src/customers@HEAD`  and read the CURRENT version of that one

A reference of either kind puts the function in the producer's execution plan, so
`@HEAD` is not a way to avoid the dependency — it is a way to say "this is the
lookup, not the trigger".

INNER keeps only orders whose customer exists — the default `how`. Note both
frames have a `country` column, so the right one arrives as `country_right`;
`suffix=` renames it, and the `select` here decides which one wins. Column
collisions in a join are a silent widening otherwise.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["src/orders@NEW", "src/customers@HEAD"],
    output_tables=["orders_enriched"],
)
def join_inner(orders: TableFrameSpec, customers: TableFrameSpec) -> TableFrameSpec:
    return orders.join(
        customers.select("customer_id", "name", "tier"),
        on="customer_id",
        how="inner",
    ).select("order_id", "customer_id", "name", "tier", "amount", "status")
