#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · src · append_only — append-only event publisher.

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.databricks import DatabricksSrc


@publisher(
    source=DatabricksSrc(queries=["SELECT * FROM brz_append_events"]),
    output_tables=["append_raw"],
)
def pub_append_events(df: TableFrameSpec) -> TableFrameSpec:
    return df
