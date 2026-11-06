#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: DERIVED COLUMNS — `with_columns`, `filter`, `lit`.

`with_columns` ADDS columns computed from expressions (or REPLACES one, if the
alias matches an existing name — which is how you fix a column in place). `filter`
cuts rows. Both are row-preserving in the sense that matters: they never build
new rows, so the system columns survive.

Expressions come from `tabsdatak.tableframe.functions`: `col` refers to a column,
`lit` wraps a CONSTANT so it can take part in an expression. `col("amount") * 1.21`
often works by coercion, but `lit` is explicit about what is data and what is a
literal — and it is required wherever the constant is on the left.

ORDER MATTERS AND SAVES WORK: `filter` first, then `with_columns`, so the
computation only runs on rows that survive. Reading the chain top to bottom is
reading the plan.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.tableframe.functions import col, lit


@transformer(input_tables=["src/orders@NEW"], output_tables=["orders_derived"])
def project_derived(orders_versions: TableFramesSpec) -> TableFrameSpec:
    orders = concat(orders_versions or [])
    return (
        orders.filter(col("status") != "cancelled")
        .with_columns(
            (col("amount") * lit(1.21)).alias("amount_with_tax"),
            (col("amount") > lit(100.0)).alias("is_large"),
        )
        .sort("amount", descending=True)
    )
