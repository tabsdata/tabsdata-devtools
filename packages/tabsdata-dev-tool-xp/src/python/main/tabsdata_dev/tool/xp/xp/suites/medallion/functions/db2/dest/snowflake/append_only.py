#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · dest · snowflake · append_only — subscribe db2 append-events fact to Snowflake.

Writes db2's append_only gold table(s) to db2_<table> in Snowflake, using the snowflake_bulk_out.yaml connection on the snowflake_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


@subscriber(
    destination=SnowflakeDest(
        tables=["db2_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["db2_in_gold/fct_append"],
)
def snow_db2_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
