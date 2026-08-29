#
# Copyright 2026 Tabsdata Inc.
#

"""mssqlserver · dest · databricks · append_only — subscribe mssqlserver append-events fact to Databricks.

Writes mssqlserver's append_only gold table(s) to mssqlserver_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["mssqlserver_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["mssqlserver_in_gold/fct_append"],
)
def sub_mssqlserver_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
