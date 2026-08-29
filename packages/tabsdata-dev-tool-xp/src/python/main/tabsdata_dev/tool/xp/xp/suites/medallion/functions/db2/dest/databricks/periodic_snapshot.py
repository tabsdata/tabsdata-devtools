#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · dest · databricks · periodic_snapshot — subscribe db2 periodic-snapshot fact to Databricks.

Writes db2's periodic_snapshot gold table(s) to db2_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["db2_fct_periodic"],
        if_table_exists="replace",
    ),
    input_tables=["db2_in_gold/fct_periodic"],
)
def sub_db2_periodic(table: TableFrameSpec) -> TableFrameSpec:
    return table
