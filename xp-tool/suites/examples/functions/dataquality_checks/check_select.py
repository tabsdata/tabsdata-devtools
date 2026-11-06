#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — DATA QUALITY: `Select`, the READ-ONLY sibling of `Filter`.

`Select(criteria, to_table=X)` COPIES the selected rows to X and leaves the
target table ALONE. Where `Filter` splits a stream, `Select` forks it.

That is the operator for a target that must stay WHOLE — an audit table, a
regulatory record, anything where dropping a row is worse than carrying a bad
one — while a downstream consumer still gets a clean subset.

Both directions are shown here, from ONE declaration: `AllOk()` copies the good
rows to `clean`, and `AnyFailed()` copies the suspect ones to `to_review` with
the verdict columns that flagged them. `audited` keeps all eight rows either way.

`to_table` is REQUIRED on `Select` — unlike `Filter`, there is no in-place form,
because copying rows onto themselves would mean nothing.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat
from tabsdatak.dataquality import (
    AllOk,
    AnyFailed,
    DataQuality,
    HasLength,
    IsBetween,
    IsIn,
    IsNotNull,
    Matches,
    Select,
)


@transformer(
    input_tables=["gen/raw_orders@NEW"],
    output_tables=["audited"],
    on_tables=[
        DataQuality(
            table="audited",
            classifiers=[
                IsNotNull(["amount"], tags=["critical"]),
                IsBetween(["amount"], min_val=0.0, max_val=100000.0, closed_on="both"),
                IsIn(["status"], values=["pending", "shipped", "cancelled"],
                     tags=["critical"]),
                Matches(["customer_email"], pattern=r"^[^@]+@[^@]+\.[a-z]+$"),
                HasLength(["country"], min_len=2, max_len=2),
            ],
            operators=[
                Select(AllOk(), to_table="clean"),
                Select(AnyFailed(), to_table="to_review",
                       include_quality_columns="criteria"),
            ],
        )
    ],
)
def check_select(orders_versions: TableFramesSpec) -> TableFrameSpec:
    orders = concat(orders_versions or [])
    return orders
