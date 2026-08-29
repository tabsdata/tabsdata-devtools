#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · bronze · periodic_snapshot — periodic-snapshot bronze (build_period_snapshot_bronze).

Part of the postgres medallion pipeline (source PostgreSQL, domain postgres_bronze_xs). Collection postgres_in_bronze; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

import tabsdatak.tableframe.datatypes as td_types
from tabsdatak._medallion.bronze.period_snapshot import (
    build_period_snapshot_bronze,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["postgres_in_src/periodic_raw@NEW"],
    output_tables=["periodic_bronze"],
)
def tfr_period_bronze(new: TableFramesSpec) -> TableFrameSpec:
    return build_period_snapshot_bronze(
        new=new,
        pk=[{"tenant_id": td_types.String}, {"entity_id": td_types.Int64}],
    )
