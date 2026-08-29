#
# Copyright 2026 Tabsdata Inc.
#

"""db2 · src · append_only — append-only event publisher.

Part of the db2 medallion pipeline (source Db2, domain db2_bronze_xs). Collection db2_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.db2 import Db2Src


@publisher(
    source=Db2Src(queries=["SELECT sim_counter AS \"sim_counter\", tenant_id AS \"tenant_id\", entity_id AS \"entity_id\", data_ts AS \"data_ts\", name AS \"name\", status AS \"status\", category AS \"category\", amount AS \"amount\", quantity AS \"quantity\", score AS \"score\", is_active AS \"is_active\" FROM brz_append_events"]),
    output_tables=["append_raw"],
)
def pub_append_events(df: TableFrameSpec) -> TableFrameSpec:
    return df
