#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · bronze · entity_scd — snapshot-diff CDC bronze (build_snapshot_diff_cdc_bronze).

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_bronze; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

import tabsdatak.tableframe.datatypes as td_types
from tabsdatak._medallion.bronze.snapshot_diff_cdc import (
    build_snapshot_diff_cdc_bronze,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=[
        "databricks_in_src/entity_raw@HEAD",
        "databricks_in_src/entity_raw@HEAD^",
        "databricks_in_src/entity_raw@NEW",
    ],
    output_tables=["entity_bronze"],
)
def tfr_entity_bronze(
    head: TableFrameSpec,
    prev: TableFrameSpec,
    new: TableFramesSpec,
) -> TableFrameSpec:
    return build_snapshot_diff_cdc_bronze(
        prev=prev,
        head=head,
        new=new,
        pk=[{"tenant_id": td_types.String}, {"entity_id": td_types.Int64}],
    )
