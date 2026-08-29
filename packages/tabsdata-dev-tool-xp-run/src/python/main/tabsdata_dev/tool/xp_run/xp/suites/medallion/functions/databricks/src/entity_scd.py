#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · src · entity_scd — snapshot publisher for the SCD entity.

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.databricks import DatabricksSrc


@publisher(
    source=DatabricksSrc(queries=["SELECT tenant_id, entity_id, data_ts, name, status, category, amount, quantity, score, is_active FROM brz_full_snapshot"]),
    output_tables=["entity_raw"],
)
def pub_entity_snapshot(df: TableFrameSpec) -> TableFrameSpec:
    return df
