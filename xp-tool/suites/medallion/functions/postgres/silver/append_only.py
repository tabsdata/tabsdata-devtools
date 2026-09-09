#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · silver · append_only — append-only silver (build_append_only_silver).

Part of the postgres medallion pipeline (source PostgreSQL, domain postgres_bronze_xs). Collection postgres_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.append_only import build_append_only_silver
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW", "append_silver@HEAD"],
    output_tables=["append_silver"],
)
def tfr_append_silver(
    bronze: TableFramesSpec,
    silver: TableFrameSpec,
) -> TableFrameSpec:
    return build_append_only_silver(bronze_new=bronze, silver_head=silver)
