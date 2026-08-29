#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · dest · snowflake · cdc — subscribe mysql CDC dimensions to Snowflake.

Writes mysql's cdc gold table(s) to mysql_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["mysql_dim_cdc_entity", "mysql_dim_cdc_entity_history", "mysql_dim_cdc_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "mysql_in_gold/dim_cdc_entity",
        "mysql_in_gold/dim_cdc_entity_history",
        "mysql_in_gold/dim_cdc_entity_ref",
    ],
)
def snow_mysql_cdc(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
