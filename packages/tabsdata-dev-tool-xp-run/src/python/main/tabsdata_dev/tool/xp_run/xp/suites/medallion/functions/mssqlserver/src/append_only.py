#
# Copyright 2026 Tabsdata Inc.
#

"""mssqlserver · src · append_only — append-only event publisher.

Part of the mssqlserver medallion pipeline (source Microsoft SQL Server, domain mssqlserver_bronze_xs). Collection mssqlserver_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.mssql import MSSQLSrc


@publisher(
    source=MSSQLSrc(queries=["SELECT * FROM brz_append_events"]),
    output_tables=["append_raw"],
)
def pub_append_events(df: TableFrameSpec) -> TableFrameSpec:
    return df
