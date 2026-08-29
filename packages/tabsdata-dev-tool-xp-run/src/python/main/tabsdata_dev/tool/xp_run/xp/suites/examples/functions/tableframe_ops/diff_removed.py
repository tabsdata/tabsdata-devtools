#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: WHAT LEFT, the same anti join with the sides swapped.

In `previous` and not in `current` -> REMOVED. Here that is customer 4.

The symmetry is the point: ONE operation answers both halves of "what changed",
and which half you get depends only on which frame you call `.join` on. Writing
both out — rather than one clever function with a flag — keeps each table's
meaning obvious at the point it is defined.

Note the input references are swapped too: `customers_previous@NEW` drives this
function, `customers@HEAD` is the lookup. In a real pipeline the driving side is
whichever table's arrival should recompute the answer.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["src/customers_previous@NEW", "src/customers@HEAD"],
    output_tables=["customers_removed"],
)
def diff_removed(previous: TableFrameSpec, current: TableFrameSpec) -> TableFrameSpec:
    return previous.join(current, on="customer_id", how="anti")
