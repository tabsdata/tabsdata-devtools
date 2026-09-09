#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · dest · databricks · entity_scd — subscribe oracle entity dimensions to Databricks.

Writes oracle's entity_scd gold table(s) to oracle_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["oracle_dim_entity", "oracle_dim_entity_history", "oracle_dim_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "oracle_in_gold/dim_entity",
        "oracle_in_gold/dim_entity_history",
        "oracle_in_gold/dim_entity_ref",
    ],
)
def sub_oracle_entity(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
