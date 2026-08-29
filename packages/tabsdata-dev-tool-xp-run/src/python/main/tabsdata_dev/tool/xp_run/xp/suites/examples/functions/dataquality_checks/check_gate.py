#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — DATA QUALITY: `Fail`, a TOLERANCE GATE, and what TAGS are for.

`Fail(criteria, threshold)` ABORTS THE TRANSACTION when the selected rows reach
the threshold. Nothing downstream ever sees the bad version — no partial table,
no half-updated warehouse. It is the strongest of the five operators and the one
to use most sparingly: a gate that fires stops the pipeline, so it should only
guard conditions that genuinely make the data unusable.

    `RowCountThreshold(1)`   zero tolerance — fail on the first bad row.
    `PercentThreshold(p)`    fail once p% of the table is selected.

WHICH IS WHERE TAGS EARN THEIR KEEP. `AnyFailed(tags=["critical"])` scopes the
gate to the classifiers marked critical, so a malformed email does NOT stop the
pipeline while a null amount or an unknown status does — and `Summary` in the
same declaration can still report on everything, or on just the tagged subset as
here. One declaration, two audiences.

THE ARITHMETIC ON THIS DATA: 2 of the 8 rows fail a critical classifier = 25%,
under the 50% tolerance below, so this run PASSES. Lower the threshold to 25 and
the transaction aborts — worth doing once to see what a gate failure looks like.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer
from tabsdatak.dataquality import (
    AnyFailed,
    DataQuality,
    Fail,
    HasLength,
    IsBetween,
    IsIn,
    IsNotNull,
    Matches,
    PercentThreshold,
    Summary,
)


@transformer(
    input_tables=["gen/raw_orders@NEW"],
    output_tables=["gated"],
    on_tables=[
        DataQuality(
            table="gated",
            classifiers=[
                IsNotNull(["amount"], tags=["critical"]),
                IsBetween(["amount"], min_val=0.0, max_val=100000.0, closed_on="both"),
                IsIn(["status"], values=["pending", "shipped", "cancelled"],
                     tags=["critical"]),
                Matches(["customer_email"], pattern=r"^[^@]+@[^@]+\.[a-z]+$"),
                HasLength(["country"], min_len=2, max_len=2),
            ],
            operators=[
                Fail(AnyFailed(tags=["critical"]), PercentThreshold(50)),
                Summary(table="critical_report", tags=["critical"]),
            ],
        )
    ],
)
def check_gate(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
