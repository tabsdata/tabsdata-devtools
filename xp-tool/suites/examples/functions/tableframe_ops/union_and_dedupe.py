#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — TableFrame: STACKING FRAMES — `concat`, and `unique` to collapse.

`concat` stacks frames vertically. The `how` is the decision:

    "vertical"   (the default) demands IDENTICAL schemas and fails otherwise.
                 Use it when a mismatch is a bug you want to hear about — two
                 monthly extracts of the same table, say.
    "diagonal"   takes the UNION of the columns and nulls the gaps. Use it when
                 the frames genuinely differ — several sources feeding one landing
                 table.

Choosing `diagonal` to make an error go away is how a schema drift becomes a
column of nulls nobody notices. Choose it because the inputs really are different.

`unique(subset=[...])` then collapses the rows the two snapshots share, keyed on
the columns you name. WITHOUT `subset` it dedupes on the WHOLE row, which is a
different question — "identical rows" rather than "same entity" — and on these
two snapshots would keep both copies of a customer whose tier had changed.

`concat` also drops `None` entries and returns `None` for an empty list, which is
why the file sources in these examples use it as their fold.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer
from tabsdatak.tableframe.functions import concat


@transformer(
    input_tables=["src/customers@NEW", "src/customers_previous@HEAD"],
    output_tables=["customers_union"],
)
def union_and_dedupe(
    current: TableFrameSpec,
    previous: TableFrameSpec,
) -> TableFrameSpec:
    return concat([current, previous], how="vertical").unique(subset=["customer_id"])
