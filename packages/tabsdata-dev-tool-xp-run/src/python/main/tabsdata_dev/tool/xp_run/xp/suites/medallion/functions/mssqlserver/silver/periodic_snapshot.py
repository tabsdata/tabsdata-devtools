#
# Copyright 2026 Tabsdata Inc.
#

"""mssqlserver · silver · periodic_snapshot — periodic-snapshot silver (build_periodic_snapshot_silver).

Part of the mssqlserver medallion pipeline (source Microsoft SQL Server, domain mssqlserver_bronze_xs). Collection mssqlserver_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.periodic_snapshot import (
    build_periodic_snapshot_silver,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["mssqlserver_in_bronze/periodic_bronze@NEW"],
    output_tables=["periodic_silver"],
)
def tfr_period_silver(bronze: TableFramesSpec) -> TableFrameSpec:
    return build_periodic_snapshot_silver(bronze)
