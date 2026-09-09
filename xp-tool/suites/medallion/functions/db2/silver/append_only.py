#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · silver · append_only — append-only silver (build_append_only_silver).

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.append_only import build_append_only_silver
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW", "append_silver@HEAD"],
    output_tables=["append_silver"],
)
def tfr_append_silver(
    bronze: TableFramesSpec,
    silver: TableFrameSpec,
) -> TableFrameSpec:
    return build_append_only_silver(bronze_new=bronze, silver_head=silver)
