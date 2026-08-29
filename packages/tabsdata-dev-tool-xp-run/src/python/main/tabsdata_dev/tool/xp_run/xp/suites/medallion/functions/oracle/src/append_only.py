#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · src · append_only — append-only event publisher.

Part of the oracle medallion pipeline (source Oracle, domain oracle_bronze_xs). Collection oracle_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.oracle import OracleSrc


@publisher(
    source=OracleSrc(queries=["SELECT sim_counter AS \"sim_counter\", tenant_id AS \"tenant_id\", entity_id AS \"entity_id\", data_ts AS \"data_ts\", name AS \"name\", status AS \"status\", category AS \"category\", amount AS \"amount\", quantity AS \"quantity\", score AS \"score\", is_active AS \"is_active\" FROM brz_append_events"]),
    output_tables=["append_raw"],
)
def pub_append_events(df: TableFrameSpec) -> TableFrameSpec:
    return df
