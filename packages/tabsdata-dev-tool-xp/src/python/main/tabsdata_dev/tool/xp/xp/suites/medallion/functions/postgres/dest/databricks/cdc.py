#
# Copyright 2026 Tabsdata Inc.
#

"""postgres · dest · databricks · cdc — subscribe postgres CDC dimensions to Databricks.

Writes postgres's cdc gold table(s) to postgres_<table> in Databricks, using the databricks_bulk_out.yaml connection on the databricks_dest collection. if_table_exists="replace" rewrites each target each run."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.databricks import DatabricksDest


@subscriber(
    destination=DatabricksDest(
        tables=["postgres_dim_cdc_entity", "postgres_dim_cdc_entity_history", "postgres_dim_cdc_entity_ref"],
        if_table_exists="replace",
    ),
    input_tables=[
        "postgres_in_gold/dim_cdc_entity",
        "postgres_in_gold/dim_cdc_entity_history",
        "postgres_in_gold/dim_cdc_entity_ref",
    ],
)
def sub_postgres_cdc(
    dim_entity: TableFrameSpec,
    dim_entity_history: TableFrameSpec,
    dim_entity_ref: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (dim_entity, dim_entity_history, dim_entity_ref)
