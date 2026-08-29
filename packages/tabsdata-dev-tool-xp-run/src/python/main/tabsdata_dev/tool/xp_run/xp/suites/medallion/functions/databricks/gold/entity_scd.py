#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · gold · entity_scd — Type1 + Type2 entity dimensions.

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_gold; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.gold.dim import build_type1_dim, build_type2_dim
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["databricks_in_silver/entity_valid_silver@HEAD"],
    output_tables=["dim_entity"],
)
def tfr_dim_entity_type1(current: TableFrameSpec) -> TableFrameSpec:
    return build_type1_dim(current)


@transformer(
    input_tables=[
        "dim_entity_history@HEAD",
        "databricks_in_silver/entity_expired_silver@NEW",
        "databricks_in_silver/entity_valid_silver@HEAD",
    ],
    output_tables=["dim_entity_history"],
)
def tfr_dim_entity_history_type2(
    history: TableFrameSpec,
    expired_new: TableFramesSpec,
    valid: TableFrameSpec,
) -> TableFrameSpec:
    if valid is None:
        return None
    return build_type2_dim(history, expired_new, valid)


@transformer(
    input_tables=["databricks_in_silver/entity_current_silver@HEAD"],
    output_tables=["dim_entity_ref"],
)
def tfr_dim_entity_ref_type1(current: TableFrameSpec) -> TableFrameSpec:
    return build_type1_dim(current)
