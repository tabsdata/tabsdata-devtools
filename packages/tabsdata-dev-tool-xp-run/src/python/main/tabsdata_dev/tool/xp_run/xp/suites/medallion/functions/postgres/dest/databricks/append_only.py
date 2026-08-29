#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · dest · databricks · append_only — subscribe postgres append-events fact to Databricks.

Writes postgres's append_only gold table(s) to postgres_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["postgres_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["postgres_in_gold/fct_append"],
)
def sub_postgres_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
