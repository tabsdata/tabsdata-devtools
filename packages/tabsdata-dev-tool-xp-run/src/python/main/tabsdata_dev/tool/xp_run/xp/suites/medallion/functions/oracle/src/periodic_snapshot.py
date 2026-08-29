#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · src · periodic_snapshot — periodic full-snapshot publisher.

Part of the oracle medallion pipeline (source Oracle, domain oracle_bronze_xs). Collection oracle_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak._medallion.constants import MEDALLION_SYSTEM_COLUMN_PERIOD
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.oracle import OracleSrc
from tabsdatak.tableframe.functions import lit


@publisher(
    source=OracleSrc(queries=["SELECT tenant_id AS \"tenant_id\", entity_id AS \"entity_id\", data_ts AS \"data_ts\", name AS \"name\", status AS \"status\", category AS \"category\", amount AS \"amount\", quantity AS \"quantity\", score AS \"score\", is_active AS \"is_active\" FROM brz_full_snapshot"]),
    output_tables=["periodic_raw"],
)
def pub_period_snapshot(df: TableFrameSpec) -> TableFrameSpec:
    # `build_period_snapshot_bronze` reads MEDALLION_SYSTEM_COLUMN_PERIOD and
    # mirrors it into MEDALLION_SYSTEM_COLUMN_SOURCE_TS; stamp it with the
    # publish time.
    now = datetime.now(tz=timezone.utc)
    return df.with_columns(lit(now).alias(MEDALLION_SYSTEM_COLUMN_PERIOD))
