#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · dest · snowflake · append_only — subscribe databricks append-events fact to Snowflake.

Writes databricks's append_only gold table(s) to databricks_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["databricks_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["databricks_in_gold/fct_append"],
)
def snow_databricks_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
