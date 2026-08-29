#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · dest · databricks · update_stream — subscribe db2 update-stream dimensions to Databricks.

Writes db2's update_stream gold table(s) to db2_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["db2_dim_upd_entity", "db2_dim_upd_entity_history", "db2_dim_upd_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "db2_in_gold/dim_upd_entity",
        "db2_in_gold/dim_upd_entity_history",
        "db2_in_gold/dim_upd_entity_ref",
    ],
)
def sub_db2_update(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
