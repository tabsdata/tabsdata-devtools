#
# Copyright 2026 Tabsdata Inc.
#

"""demo · logistics — courier operations over the `courierlogistics` sample in S3.

Three stages, one collection each:

  logistics_src   (@publisher)    read the hubs / couriers / customers / shipments
                                  / tracking_events parquet shards staged in the
                                  s3logistics domain
  logistics_marts (@transformer)  enrich shipments with sender and hubs, split
                                  in-transit and failed, build the tracking timeline
  logistics_s3    (@subscriber)   write each mart to a parquet object in S3

The seed writes one file per entity per format under the domain root,
`<fmt>/<entity>_<YYYYMMDDThhmmss_mmm>.<fmt>`, and `modify-data` adds NEW shards
alongside (never mutating the old ones) — so each path is a wildcard and each
slot, an ARRAY of frames, is folded with `concat`. `<entity>_2*` (not
`<entity>*`) keeps a wildcard from swallowing a longer-named sibling: the shard
suffix always starts with the year, so `_2` disambiguates.

The marts use the Tabsdata TableFrame API only (join / filter / select / sort /
rename) — no polars. They are ROW-PRESERVING transforms (they carry the
framework's system columns through), which is what a @transformer output must be
to sink cleanly. Statuses are the generator's vocabulary: picked_up, in_transit,
at_hub, out_for_delivery, delivered, failed, returned.
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    TableFramesSpec,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.s3 import S3Dest, S3Src
from tabsdatak.tableframe.functions import col, concat


# --- ingest: S3 courierlogistics parquet -> logistics_src --------------------
@publisher(
    source=S3Src(
        paths=[
            "parquet/hubs_2*.parquet",
            "parquet/couriers_2*.parquet",
            "parquet/customers_2*.parquet",
            "parquet/shipments_2*.parquet",
            "parquet/tracking_events_2*.parquet",
        ],
    ),
    output_tables=["hubs", "couriers", "customers", "shipments", "tracking_events"],
)
def pub_logistics(
    hubs: TableFramesSpec,
    couriers: TableFramesSpec,
    customers: TableFramesSpec,
    shipments: TableFramesSpec,
    tracking_events: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    # Each slot is an array (one frame per matched shard); `concat` unions them.
    # Vertical (the strict default) on purpose: a shard whose schema drifted
    # should surface here rather than be absorbed silently.
    return (
        concat(hubs),
        concat(couriers),
        concat(customers),
        concat(shipments),
        concat(tracking_events),
    )


# --- marts: enrichment joins + filters (logistics_src -> logistics_marts) -----
@transformer(
    input_tables=[
        "logistics_src/shipments@HEAD",
        "logistics_src/customers@HEAD",
        "logistics_src/hubs@HEAD",
    ],
    output_tables=["shipments_enriched"],
)
def tfr_shipments_enriched(
    shipments: TableFrameSpec, customers: TableFrameSpec, hubs: TableFrameSpec
) -> TableFrameSpec:
    # shipment -> sender (customer) -> origin hub -> destination hub. The hubs table
    # is joined TWICE, so each side is renamed to its role first — otherwise the
    # second join would suffix the colliding columns `_right`.
    sender = customers.select("customer_id", "name", "account_type").rename(
        {"name": "sender_name"}
    )
    origin = hubs.select("hub_id", "code", "city").rename(
        {"code": "origin_hub", "city": "origin_city"}
    )
    destination = hubs.select("hub_id", "code", "city").rename(
        {"code": "dest_hub", "city": "dest_city"}
    )
    enriched = shipments.join(sender, left_on="sender_id", right_on="customer_id", how="left")
    enriched = enriched.join(origin, left_on="origin_hub_id", right_on="hub_id", how="left")
    enriched = enriched.join(destination, left_on="dest_hub_id", right_on="hub_id", how="left")
    return enriched.select(
        "shipment_id",
        "tracking_no",
        "sender_name",
        "account_type",
        "recipient_name",
        "origin_hub",
        "origin_city",
        "dest_hub",
        "dest_city",
        "weight_kg",
        "service_type",
        "declared_value",
        "status",
        "created_at",
        "estimated_delivery",
    )


@transformer(
    input_tables=["logistics_marts/shipments_enriched@HEAD"],
    output_tables=["in_transit_shipments"],
)
def tfr_in_transit_shipments(enriched: TableFrameSpec) -> TableFrameSpec:
    # What is on the road right now, earliest promised delivery first.
    return enriched.filter(col("status") == "in_transit").sort("estimated_delivery")


@transformer(
    input_tables=["logistics_marts/shipments_enriched@HEAD"],
    output_tables=["failed_deliveries"],
)
def tfr_failed_deliveries(enriched: TableFrameSpec) -> TableFrameSpec:
    # Shipments whose last event was an exception or a failed attempt, the most
    # valuable first — the follow-up queue.
    return enriched.filter(col("status") == "failed").sort("declared_value", descending=True)


@transformer(
    input_tables=[
        "logistics_src/tracking_events@HEAD",
        "logistics_src/shipments@HEAD",
        "logistics_src/hubs@HEAD",
        "logistics_src/couriers@HEAD",
    ],
    output_tables=["tracking_timeline"],
)
def tfr_tracking_timeline(
    tracking_events: TableFrameSpec,
    shipments: TableFrameSpec,
    hubs: TableFrameSpec,
    couriers: TableFrameSpec,
) -> TableFrameSpec:
    # Every scan event with the shipment's tracking number, the hub it happened at
    # and the courier who handled it, per shipment in occurrence order. Hub and
    # courier are nullable on an event (not every event has both), hence left joins.
    timeline = tracking_events.join(
        shipments.select("shipment_id", "tracking_no", "service_type"),
        on="shipment_id",
        how="left",
    )
    timeline = timeline.join(
        hubs.select("hub_id", "code").rename({"code": "hub_code"}), on="hub_id", how="left"
    )
    timeline = timeline.join(
        couriers.select("courier_id", "name", "vehicle_type").rename({"name": "courier_name"}),
        on="courier_id",
        how="left",
    )
    return timeline.select(
        "event_id",
        "shipment_id",
        "tracking_no",
        "service_type",
        "event_type",
        "hub_code",
        "courier_name",
        "vehicle_type",
        "location_desc",
        "occurred_at",
    ).sort("shipment_id", "occurred_at")


# --- serve: one parquet object per mart (logistics_marts -> S3) -------------
# Paths are relative to the s3 domain's base path; every run of a mart overwrites
# its object, so the bucket always holds the latest view.
@subscriber(
    destination=S3Dest(paths=["logistics/shipments_enriched.parquet"]),
    input_tables=["logistics_marts/shipments_enriched"],
)
def sink_shipments_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["logistics/in_transit_shipments.parquet"]),
    input_tables=["logistics_marts/in_transit_shipments"],
)
def sink_in_transit_shipments(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["logistics/failed_deliveries.parquet"]),
    input_tables=["logistics_marts/failed_deliveries"],
)
def sink_failed_deliveries(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["logistics/tracking_timeline.parquet"]),
    input_tables=["logistics_marts/tracking_timeline"],
)
def sink_tracking_timeline(t: TableFrameSpec) -> TableFrameSpec:
    return t
