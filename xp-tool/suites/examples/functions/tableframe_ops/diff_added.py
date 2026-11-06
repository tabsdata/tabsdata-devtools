#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: WHAT ARRIVED, via an ANTI JOIN.

THERE IS NO `.diff()` ON A FRAME. A row-level difference IS a join:

    `how="anti"`  keep the left rows with NO match on the right
    `how="semi"`  keep the left rows WITH a match

Neither adds the right side's columns, so the result has exactly the LEFT frame's
shape — which is what makes them composable, and what separates them from a left
join plus a null filter (that version drags the right side's columns along and
has to drop them again).

In `current` and not in `previous` -> ARRIVED. Here that is customer 5.

`diff_removed.py` is the same call with the sides swapped, and `diff_kept.py` is
the semi version. A full "what changed" report is those three plus a value
comparison over the intersection.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat


@transformer(
    input_tables=["src/customers@NEW", "src/customers_previous@HEAD"],
    output_tables=["customers_added"],
)
def diff_added(current_versions: TableFramesSpec, previous: TableFrameSpec) -> TableFrameSpec:
    current = concat(current_versions or [])
    return current.join(previous, on="customer_id", how="anti")
