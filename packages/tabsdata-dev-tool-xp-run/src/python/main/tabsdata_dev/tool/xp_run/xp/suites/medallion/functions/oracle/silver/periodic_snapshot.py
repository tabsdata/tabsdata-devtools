#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · silver · periodic_snapshot — periodic-snapshot silver (build_periodic_snapshot_silver).

Part of the oracle medallion pipeline (source Oracle, domain oracle_bronze_xs). Collection oracle_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.periodic_snapshot import (
    build_periodic_snapshot_silver,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["oracle_in_bronze/periodic_bronze@NEW"],
    output_tables=["periodic_silver"],
)
def tfr_period_silver(bronze: TableFramesSpec) -> TableFrameSpec:
    return build_periodic_snapshot_silver(bronze)
