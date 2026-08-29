#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · gold · periodic_snapshot — periodic-snapshot fact (build_fact).

Part of the postgres medallion pipeline (source PostgreSQL, domain postgres_bronze_xs). Collection postgres_in_gold; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.gold.fact import build_fact
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["postgres_in_silver/periodic_silver@NEW", "dim_entity_history@HEAD"],
    output_tables=["fct_periodic"],
)
def tfr_fct_periodic(
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
