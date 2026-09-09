#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · dest · snowflake · update_stream — subscribe db2 update-stream dimensions to Snowflake.

Writes db2's update_stream gold table(s) to db2_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["db2_dim_upd_entity", "db2_dim_upd_entity_history", "db2_dim_upd_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "db2_in_gold/dim_upd_entity",
        "db2_in_gold/dim_upd_entity_history",
        "db2_in_gold/dim_upd_entity_ref",
    ],
)
def snow_db2_update(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
