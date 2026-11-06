#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — DATA QUALITY: `Filter`, which QUARANTINES rather than deletes.

`Filter(criteria)` REMOVES the rows the criteria selects from the target table.
On its own that is a delete — the rows are discarded. `Filter(criteria,
to_table=X)` REDIRECTS them to X instead, which is almost always what you want:
the good rows carry on down the pipeline and the bad ones become a table you can
look at, alert on, and subscribe to.

`include_quality_columns` decides how much explanation travels with them:
`"none"` (the default), `"criteria"` (the verdict columns the criteria consulted)
or `"all"`. Use `"all"` on a quarantine table — a rejected row without the
verdict that rejected it is a support ticket.

AN OPERATOR THAT NAMES A TABLE REGISTERS THAT TABLE in the same collection. So
`rejected` and `screened_report` below are real tables, exactly like a function's
own outputs, and downstream functions can depend on them.

`AnyFailed()` selects rows where at least one boolean classifier came back false.
By default a null or NaN verdict COUNTS AS A FAILURE; `none_is_ok=True` /
`nan_is_ok=True` let them pass. `AllOk()` is its complement.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.dataquality import (
    AnyFailed,
    DataQuality,
    Filter,
    HasLength,
    IsBetween,
    IsIn,
    IsNotNull,
    Matches,
    Summary,
)


@transformer(
    input_tables=["gen/raw_orders@NEW"],
    output_tables=["screened"],
    on_tables=[
        DataQuality(
            table="screened",
            classifiers=[
                IsNotNull(["amount"], tags=["critical"]),
                IsBetween(["amount"], min_val=0.0, max_val=100000.0, closed_on="both"),
                IsIn(["status"], values=["pending", "shipped", "cancelled"],
                     tags=["critical"]),
                Matches(["customer_email"], pattern=r"^[^@]+@[^@]+\.[a-z]+$"),
                HasLength(["country"], min_len=2, max_len=2),
            ],
            operators=[
                Filter(AnyFailed(), to_table="rejected",
                       include_quality_columns="all"),
                Summary(table="screened_report"),
            ],
        )
    ],
)
def check_quarantine(orders_versions: TableFramesSpec) -> TableFrameSpec:
    # `screened` comes out holding only the rows that passed everything;
    # `rejected` holds the three that did not, with the verdicts that explain
    # why.
    orders = concat(orders_versions or [])
    return orders
