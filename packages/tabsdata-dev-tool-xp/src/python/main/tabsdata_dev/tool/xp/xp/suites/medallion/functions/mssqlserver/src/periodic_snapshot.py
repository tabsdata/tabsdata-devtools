#
# Copyright 2026 Tabsdata Inc.
#

"""mssqlserver · src · periodic_snapshot — periodic full-snapshot publisher.

Part of the mssqlserver medallion pipeline (source Microsoft SQL Server, domain mssqlserver_bronze_xs). Collection mssqlserver_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak._medallion.constants import MEDALLION_SYSTEM_COLUMN_PERIOD
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.mssql import MSSQLSrc
from tabsdatak.tableframe.functions import lit


@publisher(
    source=MSSQLSrc(queries=["SELECT tenant_id, entity_id, data_ts, name, status, category, amount, quantity, score, is_active FROM brz_full_snapshot"]),
    output_tables=["periodic_raw"],
)
def pub_period_snapshot(df: TableFrameSpec) -> TableFrameSpec:
    # `build_period_snapshot_bronze` reads MEDALLION_SYSTEM_COLUMN_PERIOD and
    # mirrors it into MEDALLION_SYSTEM_COLUMN_SOURCE_TS; stamp it with the
    # publish time.
    now = datetime.now(tz=timezone.utc)
    return df.with_columns(lit(now).alias(MEDALLION_SYSTEM_COLUMN_PERIOD))
