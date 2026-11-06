#
# Copyright 2026 Tabsdata Inc.
#

"""showcase · retail — a self-contained synthetic pipeline landing in the cloud.

Three stages, one collection each:

  retail_src  (@publisher)    generate small `customers` / `orders` frames in-process
                              via the dev DataGenSrc (no external system to seed)
  retail_marts(@transformer)  enrich + filter into serving views
  retail_out  (@subscriber)   write each view out to S3 as parquet

DataGenSrc is the ONE place polars appears — it needs literal ``pl.DataFrame``s to
generate from. Every transform uses the Tabsdata TableFrame API only (join / filter
/ select / sort) — no polars. These are ROW-PRESERVING transforms (they carry the
framework's system columns through), which is the shape that sinks reliably.
"""
from __future__ import annotations

import polars as pl  # DataGenSrc input only — never used in a transform.

from tabsdatak.api import (
    TableFrameSpec, TableFramesSpec,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.tableframe.functions import concat
from tabsdatak.conn.clickhouse import ClickHouseDest
from tabsdatak.conn.dev import Data, DataGenSrc
from tabsdatak.conn.s3 import S3Dest
from tabsdatak.tableframe.functions import col


# --- synthetic source data (DataGenSrc needs literal polars frames) ----------
_CUSTOMERS = pl.DataFrame(
    {
        "customer_id": [1, 2, 3, 4, 5, 6],
        "name": ["Ada", "Bao", "Cora", "Diego", "Eun", "Fatima"],
        "country": ["US", "US", "ES", "JP", "KR", "MA"],
    }
)
_ORDERS = pl.DataFrame(
    {
        "order_id": [101, 102, 103, 104, 105, 106, 107, 108],
        "customer_id": [1, 1, 2, 3, 3, 3, 5, 6],
        "amount": [120.0, 80.0, 200.0, 50.0, 75.0, 25.0, 300.0, 60.0],
        "status": ["paid", "paid", "paid", "refunded", "paid", "paid", "paid", "paid"],
    }
)


# --- ingest: dev DataGenSrc -> retail_src ------------------------------------
@publisher(
    source=DataGenSrc(data=[Data(_CUSTOMERS), Data(_ORDERS)]),
    output_tables=["customers", "orders"],
)
def pub_retail(
    customers: TableFrameSpec, orders: TableFrameSpec
) -> tuple[TableFrameSpec, TableFrameSpec]:
    # DataGenSrc is single-mode: one frame per Data slot.
    return (customers, orders)


# --- marts: enrich + filter (retail_src -> retail_marts) ---------------------
@transformer(
    input_tables=["retail_src/orders@NEW", "retail_src/customers@HEAD"],
    output_tables=["orders_enriched"],
)
def tfr_orders_enriched(
    orders_versions: TableFramesSpec, customers: TableFrameSpec
) -> TableFrameSpec:
    # Attach each order's customer name and country (orders -> customers).
    orders = concat(orders_versions or [])
    return orders.join(customers, on="customer_id", how="left").select(
        "order_id", "customer_id", "name", "country", "amount", "status"
    )


@transformer(
    input_tables=["retail_src/orders@NEW", "retail_src/customers@HEAD"],
    output_tables=["paid_orders"],
)
def tfr_paid_orders(
    orders_versions: TableFramesSpec, customers: TableFrameSpec
) -> TableFrameSpec:
    # Paid orders only, enriched with the customer, biggest first.
    orders = concat(orders_versions or [])
    return (
        orders.filter(col("status") == "paid")
        .join(customers, on="customer_id", how="left")
        .select("order_id", "name", "country", "amount")
        .sort("amount", descending=True)
    )


# --- serve: one mart sink per table (retail_marts -> S3 parquet) -------------
@subscriber(
    destination=S3Dest(paths=["orders_enriched.parquet"]),
    input_tables=["retail_marts/orders_enriched"],
)
def sink_orders_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["paid_orders.parquet"]),
    input_tables=["retail_marts/paid_orders"],
)
def sink_paid_orders(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- serve (warehouse): the same marts bulk-loaded into ClickHouse -----------
# One mart sink per table. Targets land in the database of the `ch` domain's
# connection, staged through the S3 bucket of the `ch_stage` domain (D1).
@subscriber(
    destination=ClickHouseDest(tables=["orders_enriched"], if_table_exists="replace"),
    input_tables=["retail_marts/orders_enriched"],
)
def ch_orders_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=ClickHouseDest(tables=["paid_orders"], if_table_exists="replace"),
    input_tables=["retail_marts/paid_orders"],
)
def ch_paid_orders(t: TableFrameSpec) -> TableFrameSpec:
    return t
