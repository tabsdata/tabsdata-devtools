#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · dest · snowflake · periodic_snapshot — subscribe databricks periodic-snapshot fact to Snowflake.

Writes databricks's periodic_snapshot gold table(s) to databricks_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["databricks_fct_periodic"],
        if_table_exists="replace",
    ),
    input_tables=["databricks_in_gold/fct_periodic"],
)
def snow_databricks_periodic(table: TableFrameSpec) -> TableFrameSpec:
    return table
