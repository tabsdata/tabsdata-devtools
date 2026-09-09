#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · dest · databricks · entity_scd — subscribe mysql entity dimensions to Databricks.

Writes mysql's entity_scd gold table(s) to mysql_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["mysql_dim_entity", "mysql_dim_entity_history", "mysql_dim_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "mysql_in_gold/dim_entity",
        "mysql_in_gold/dim_entity_history",
        "mysql_in_gold/dim_entity_ref",
    ],
)
def sub_mysql_entity(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
