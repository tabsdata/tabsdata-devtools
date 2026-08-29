#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · dest · snowflake · update_stream — subscribe postgres update-stream dimensions to Snowflake.

Writes postgres's update_stream gold table(s) to postgres_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["postgres_dim_upd_entity", "postgres_dim_upd_entity_history", "postgres_dim_upd_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "postgres_in_gold/dim_upd_entity",
        "postgres_in_gold/dim_upd_entity_history",
        "postgres_in_gold/dim_upd_entity_ref",
    ],
)
def snow_postgres_update(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
