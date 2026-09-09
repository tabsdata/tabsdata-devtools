#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · src · append_only — append-only event publisher.

Part of the mysql medallion pipeline (source MySQL, domain mysql_bronze_xs). Collection mysql_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.mysql import MySQLSrc


@publisher(
    source=MySQLSrc(queries=["SELECT * FROM brz_append_events"]),
    output_tables=["append_raw"],
)
def pub_append_events(df: TableFrameSpec) -> TableFrameSpec:
    return df
