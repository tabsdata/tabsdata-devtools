#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · dest · databricks · periodic_snapshot — subscribe databricks periodic-snapshot fact to Databricks.

Writes databricks's periodic_snapshot gold table(s) to databricks_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["databricks_fct_periodic"],
        if_table_exists="replace",
    ),
    input_tables=["databricks_in_gold/fct_periodic"],
)
def sub_databricks_periodic(table: TableFrameSpec) -> TableFrameSpec:
    return table
