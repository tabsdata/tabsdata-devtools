#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · silver · periodic_snapshot — periodic-snapshot silver (build_periodic_snapshot_silver).

Part of the postgres medallion pipeline (source PostgreSQL, domain postgres_bronze_xs). Collection postgres_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.periodic_snapshot import (
    build_periodic_snapshot_silver,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["postgres_in_bronze/periodic_bronze@NEW"],
    output_tables=["periodic_silver"],
)
def tfr_period_silver(bronze: TableFramesSpec) -> TableFrameSpec:
    return build_periodic_snapshot_silver(bronze)
