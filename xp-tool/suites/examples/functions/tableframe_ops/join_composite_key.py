#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: a COMPOSITE JOIN KEY.

`on` takes a LIST when the key is more than one column. Use `left_on=` /
`right_on=` instead when the two sides spell the key differently — they take
lists too.

A composite key is also the fix for the accidental-fan-out problem: joining on a
key that is not unique on the right multiplies rows. If a join returns more rows
than the left side had and you did not expect it, the key is too narrow.

Here the join is on `(customer_id, country)`, which both frames carry — so it
also quietly removes the `country_right` collision the single-key version has.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat


@transformer(
    input_tables=["src/orders@NEW", "src/customers@HEAD"],
    output_tables=["orders_same_country"],
)
def join_composite_key(
    orders_versions: TableFramesSpec,
    customers: TableFrameSpec,
) -> TableFrameSpec:
    orders = concat(orders_versions or [])
    return orders.join(
        customers.select("customer_id", "country", "name"),
        on=["customer_id", "country"],
        how="inner",
    )
