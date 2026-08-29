#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · dest · snowflake · append_only — subscribe mysql append-events fact to Snowflake.

Writes mysql's append_only gold table(s) to mysql_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["mysql_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["mysql_in_gold/fct_append"],
)
def snow_mysql_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
