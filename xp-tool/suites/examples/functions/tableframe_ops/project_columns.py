#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: PROJECTION — `select`, `rename`, `sort`.

`select` PICKS columns and fixes their ORDER; `rename` maps old names to new;
`drop` is select's complement (name what goes, keep the rest). All three are
ROW-PRESERVING: they map rows one-to-one, so the framework's system columns come
through with them and the result sinks cleanly.

PROJECT EARLY. A `select` right after a read is the cheapest optimisation
available — every later join, sort and write moves less data — and it also pins
the contract: a column added upstream cannot silently appear downstream.

`rename` at the boundary is how a source's vocabulary stops being your
warehouse's. Do it once, here, rather than in every consumer.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat


@transformer(input_tables=["src/customers@NEW"], output_tables=["customer_labels"])
def project_columns(customers_versions: TableFramesSpec) -> TableFrameSpec:
    customers = concat(customers_versions or [])
    return (
        customers.select("customer_id", "name", "country")
        .rename({"name": "customer_name"})
        .sort("customer_id")
    )
