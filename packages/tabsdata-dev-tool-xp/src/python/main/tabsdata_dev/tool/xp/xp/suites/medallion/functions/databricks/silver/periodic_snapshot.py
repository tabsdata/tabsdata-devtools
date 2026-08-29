#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · silver · periodic_snapshot — periodic-snapshot silver (build_periodic_snapshot_silver).

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.periodic_snapshot import (
    build_periodic_snapshot_silver,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["databricks_in_bronze/periodic_bronze@NEW"],
    output_tables=["periodic_silver"],
)
def tfr_period_silver(bronze: TableFramesSpec) -> TableFrameSpec:
    return build_periodic_snapshot_silver(bronze)
