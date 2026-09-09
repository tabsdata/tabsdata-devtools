#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · dest · snowflake · entity_scd — subscribe databricks entity dimensions to Snowflake.

Writes databricks's entity_scd gold table(s) to databricks_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["databricks_dim_entity", "databricks_dim_entity_history", "databricks_dim_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "databricks_in_gold/dim_entity",
        "databricks_in_gold/dim_entity_history",
        "databricks_in_gold/dim_entity_ref",
    ],
)
def snow_databricks_entity(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
