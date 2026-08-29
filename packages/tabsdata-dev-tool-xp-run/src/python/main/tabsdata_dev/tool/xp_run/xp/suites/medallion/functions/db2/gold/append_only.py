#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · gold · append_only — append-events fact (build_fact).

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_gold; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.gold.fact import build_fact
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["db2_in_silver/append_silver@NEW", "dim_entity_history@HEAD"],
    output_tables=["fct_append"],
)
def tfr_fct_append(
    rows: TableFramesSpec,
    entity_history: TableFrameSpec,
) -> TableFrameSpec:
    if entity_history is None:
        return None
    return build_fact(
        rows,
        dim_versions=[
            (entity_history, ["tenant_id", "entity_id"], "entity_version_sk")
        ],
    )
