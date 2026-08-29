#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · bronze · cdc — CDC bronze merge (build_cdc_bronze).

Part of the postgres medallion pipeline (source PostgreSQL, domain postgres_bronze_xs). Collection postgres_in_bronze; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

import tabsdatak.tableframe.datatypes as td_types
from tabsdatak._medallion.bronze.cdc import build_cdc_bronze
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["postgres_in_src/cdc_full_raw@NEW", "postgres_in_cdc_src/cdc_raw@NEW"],
    output_tables=["cdc_bronze"],
)
def tfr_cdc_bronze(
    full_commits: TableFramesSpec,
    cdc_commits: TableFramesSpec,
) -> TableFrameSpec:
    return build_cdc_bronze(
        full_commits=full_commits,
        cdc_commits=cdc_commits,
        pk=[{"tenant_id": td_types.String}, {"entity_id": td_types.Int64}],
    )
