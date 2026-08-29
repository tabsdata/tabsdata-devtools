#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · dest · databricks · append_only — subscribe db2 append-events fact to Databricks.

Writes db2's append_only gold table(s) to db2_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["db2_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["db2_in_gold/fct_append"],
)
def sub_db2_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
