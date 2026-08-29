#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · dest · snowflake · periodic_snapshot — subscribe mysql periodic-snapshot fact to Snowflake.

Writes mysql's periodic_snapshot gold table(s) to mysql_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["mysql_fct_periodic"],
        if_table_exists="replace",
    ),
    input_tables=["mysql_in_gold/fct_periodic"],
)
def snow_mysql_periodic(table: TableFrameSpec) -> TableFrameSpec:
    return table
