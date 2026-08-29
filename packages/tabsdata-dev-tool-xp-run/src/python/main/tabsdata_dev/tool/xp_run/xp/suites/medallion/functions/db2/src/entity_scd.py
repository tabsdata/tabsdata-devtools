#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · src · entity_scd — snapshot publisher for the SCD entity.

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(queries=["SELECT tenant_id AS \"tenant_id\", entity_id AS \"entity_id\", data_ts AS \"data_ts\", name AS \"name\", status AS \"status\", category AS \"category\", amount AS \"amount\", quantity AS \"quantity\", score AS \"score\", is_active AS \"is_active\" FROM brz_full_snapshot"]),
    output_tables=["entity_raw"],
)
def pub_entity_snapshot(df: TableFrameSpec) -> TableFrameSpec:
    return df
