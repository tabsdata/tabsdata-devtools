#
# Copyright 2026 Tabsdata Inc.
#

"""databricks · src · update_stream — bootstrap + incremental update-stream publishers.

Part of the databricks medallion pipeline (source Databricks, domain databricks_bronze_xs). Collection databricks_in_src; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from datetime import timezone

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher
from tabsdatak.conn.databricks import DatabricksSrc


@publisher(
    source=DatabricksSrc(queries=["SELECT * FROM brz_insup_soft_delete"]),
    output_tables=["update_full_raw"],
)
def pub_upd_full(df: TableFrameSpec) -> TableFrameSpec:
    return df


@publisher(
    source=DatabricksSrc(queries=["SELECT * FROM brz_insup_soft_delete WHERE data_ts > timestamp_seconds(:wm) ORDER BY data_ts"], initial_values={"wm": 0}),
    output_tables=["update_raw"],
)
def pub_upd_stream(df: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if df is not None:
        # Advance the watermark to the batch's max data_ts as epoch seconds. max_for
        # returns the highest-ranked row's columns as a {col: value} dict, or None on
        # an empty batch (paging holds its place instead of rewinding). The value
        # reads back as a naive datetime; treat it as UTC.
        row = df.max_for("data_ts")
        if row is not None and row["data_ts"] is not None:
            ctx.set_attr("wm", int(row["data_ts"].replace(tzinfo=timezone.utc).timestamp()))
    return df
