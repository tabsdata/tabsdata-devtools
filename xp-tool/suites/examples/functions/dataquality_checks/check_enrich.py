#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — DATA QUALITY: `Enrich` + `Summary`, the non-destructive starting pair.

HOW A CHECK IS WIRED. It is not code you call; it is a DECLARATION on the
decorator:

    @transformer(..., on_tables=[DataQuality(table=..., classifiers=[...],
                                             operators=[...])])

The runtime runs it against the named OUTPUT table AFTER the function succeeds.
`on_tables` works the same on `@publisher` and `@subscriber` — check at ingest,
after a transform, or on the way out. The transform here is a PASS-THROUGH on
purpose: the declaration is the subject.

THE TWO HALVES

    CLASSIFIERS  label each ROW of the named columns: `IsNotNull`, `IsBetween`,
                 `IsIn`, `Matches`, `HasLength`, `IsPositive`, `IsNull`, ... plus
                 CATEGORIZERS (`ScaleCategorizer`, `InBins`) that bucket rather
                 than pass/fail. A verdict lands in `<column>_<classifier>`
                 unless a `(column, verdict_column)` tuple names it.
    OPERATORS    act on those labels: `Enrich`, `Summary`, `Filter`, `Select`,
                 `Fail`.

A VERDICT IS A `UInt8`, NOT A BOOL: `1` true, `0` false, and the reserved
sentinels `255` null, `254` NaN, `253` overflow, `252` underflow. So "failed" and
"could not be evaluated" stay distinguishable — which is why the criteria in the
other files take `none_is_ok` / `nan_is_ok` flags.

`Enrich()` appends the verdict columns IN PLACE and removes nothing.
`Enrich(to_table=X)` writes the enriched rows to a new table X instead. Start
here: it is the operator that cannot lose data.

`Summary()` emits one row per classifier — the tallies — into
`<target>_dq_summary`, or into `Summary(table=X)`. That is what you chart or
alert on.

TAGS: every classifier takes `tags=[...]`, and `Summary`, `Enrich` and the
criteria take `tags=` to select by them. One declaration can then serve two
audiences — see `check_gate.py`.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer
from tabsdatak.dataquality import (
    DataQuality,
    Enrich,
    HasLength,
    IsBetween,
    IsIn,
    IsNotNull,
    Matches,
    Summary,
)


@transformer(
    input_tables=["gen/raw_orders@NEW"],
    output_tables=["orders"],
    on_tables=[
        DataQuality(
            table="orders",
            classifiers=[
                IsNotNull(["amount"], tags=["critical"]),
                IsBetween(["amount"], min_val=0.0, max_val=100000.0, closed_on="both"),
                IsIn(["status"], values=["pending", "shipped", "cancelled"],
                     tags=["critical"]),
                Matches(["customer_email"], pattern=r"^[^@]+@[^@]+\.[a-z]+$"),
                HasLength(["country"], min_len=2, max_len=2),
            ],
            operators=[Enrich(), Summary()],
        )
    ],
)
def check_enrich(orders: TableFrameSpec) -> TableFrameSpec:
    return orders
