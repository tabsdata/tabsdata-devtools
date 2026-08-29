#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · dest · databricks · periodic_snapshot — subscribe mysql periodic-snapshot fact to Databricks.

Writes mysql's periodic_snapshot gold table(s) to mysql_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["mysql_fct_periodic"],
        if_table_exists="replace",
    ),
    input_tables=["mysql_in_gold/fct_periodic"],
)
def sub_mysql_periodic(table: TableFrameSpec) -> TableFrameSpec:
    return table
