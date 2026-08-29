#
# Copyright 2026 Tabsdata Inc.
#

"""mssqlserver · dest · snowflake · append_only — subscribe mssqlserver append-events fact to Snowflake.

Writes mssqlserver's append_only gold table(s) to mssqlserver_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["mssqlserver_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["mssqlserver_in_gold/fct_append"],
)
def snow_mssqlserver_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
