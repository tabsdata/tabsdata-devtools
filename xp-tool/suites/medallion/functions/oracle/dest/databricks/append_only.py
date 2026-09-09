#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · dest · databricks · append_only — subscribe oracle append-events fact to Databricks.

Writes oracle's append_only gold table(s) to oracle_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["oracle_fct_append"],
        if_table_exists="replace",
    ),
    input_tables=["oracle_in_gold/fct_append"],
)
def sub_oracle_append(table: TableFrameSpec) -> TableFrameSpec:
    return table
