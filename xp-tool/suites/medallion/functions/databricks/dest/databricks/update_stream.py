#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · dest · databricks · update_stream — subscribe databricks update-stream dimensions to Databricks.

Writes databricks's update_stream gold table(s) to databricks_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["databricks_dim_upd_entity", "databricks_dim_upd_entity_history", "databricks_dim_upd_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "databricks_in_gold/dim_upd_entity",
        "databricks_in_gold/dim_upd_entity_history",
        "databricks_in_gold/dim_upd_entity_ref",
    ],
)
def sub_databricks_update(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
