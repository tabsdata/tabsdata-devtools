#
# Copyright 2026 Tabsdata Inc.
#

"""showcase · airport — airline operations over the `airportdb` sample.

Three stages, one collection each:

  airport_src  (@publisher)    read flight / booking / passenger / airline
                               parquet from a local-file source (seeded airportdb)
  airport_marts(@transformer)  enrich bookings/flights and filter high-value bookings
  airport_out  (@subscriber)   write each view out to a local parquet file

Shows multi-table enrichment joins and filtering with the Tabsdata TableFrame API
only (join / filter / select / sort) — no polars. These are ROW-PRESERVING
transforms (carry the framework's system columns through). File sources bind ARRAY
mode (a path may glob), so each single-file slot is indexed ``[0]``.
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    TableFramesSpec,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.databricks import DatabricksDest
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe.functions import col


# --- ingest: local-file airportdb parquet -> airport_src ---------------------
@publisher(
    source=LocalFileSrc(
        # The airportdb seed writes timestamped, possibly-duplicated shards per
        # table (`<table>_<YYYYMMDDThhmmss_mmm>.parquet`), so each entry globs.
        # `<table>_2*` (not `<table>*`) keeps the `flight`/`passenger` slots from
        # also swallowing the `flight_schedule`/`passenger_details` shards — the
        # shard suffix always starts with the year, so `_2` disambiguates.
        paths=[
            "parquet/flight_2*.parquet",
            "parquet/booking_2*.parquet",
            "parquet/passenger_2*.parquet",
            "parquet/airline_2*.parquet",
        ],
    ),
    output_tables=["flight", "booking", "passenger", "airline"],
)
def pub_airport(
    flight: TableFramesSpec,
    booking: TableFramesSpec,
    passenger: TableFramesSpec,
    airline: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    # Each glob resolves to one file, so each slot is a 1-element array -> slot[0].
    return (flight[0], booking[0], passenger[0], airline[0])


# --- marts: enrichment joins + filter (airport_src -> airport_marts) ---------
@transformer(
    input_tables=[
        "airport_src/booking@NEW",
        "airport_src/passenger@HEAD",
        "airport_src/flight@HEAD",
        "airport_src/airline@HEAD",
    ],
    output_tables=["bookings_enriched"],
)
def tfr_bookings_enriched(
    booking: TableFrameSpec,
    passenger: TableFrameSpec,
    flight: TableFrameSpec,
    airline: TableFrameSpec,
) -> TableFrameSpec:
    # booking -> passenger (name) -> flight (flightno, airline_id) -> airline (name).
    enriched = booking.join(
        passenger.select("passenger_id", "firstname", "lastname"),
        on="passenger_id",
        how="left",
    )
    enriched = enriched.join(
        flight.select("flight_id", "flightno", "airline_id"), on="flight_id", how="left"
    )
    enriched = enriched.join(
        airline.select("airline_id", "airline_name"), on="airline_id", how="left"
    )
    return enriched.select(
        "booking_id", "firstname", "lastname", "flightno", "airline_name", "seat", "price"
    )


@transformer(input_tables=["airport_src/booking@NEW"], output_tables=["high_value_bookings"])
def tfr_high_value_bookings(booking: TableFrameSpec) -> TableFrameSpec:
    # Bookings above a price threshold, most expensive first.
    return (
        booking.filter(col("price") > 500)
        .select("booking_id", "flight_id", "passenger_id", "seat", "price")
        .sort("price", descending=True)
    )


@transformer(
    input_tables=["airport_src/flight@NEW", "airport_src/airline@HEAD"],
    output_tables=["flight_roster"],
)
def tfr_flight_roster(flight: TableFrameSpec, airline: TableFrameSpec) -> TableFrameSpec:
    # Flights with their operating airline's name.
    return flight.join(
        airline.select("airline_id", "airline_name"), on="airline_id", how="left"
    ).select("flight_id", "flightno", "from_airport", "to_airport", "departure", "airline_name")


# --- serve: one view sink per table (airport_marts -> local parquet) ---------
@subscriber(
    destination=LocalFileDest(paths=["bookings_enriched.parquet"]),
    input_tables=["airport_marts/bookings_enriched"],
)
def sink_bookings_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["high_value_bookings.parquet"]),
    input_tables=["airport_marts/high_value_bookings"],
)
def sink_high_value_bookings(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=LocalFileDest(paths=["flight_roster.parquet"]),
    input_tables=["airport_marts/flight_roster"],
)
def sink_flight_roster(t: TableFrameSpec) -> TableFrameSpec:
    return t


# --- serve (warehouse): the same marts bulk-loaded into Databricks -----------
# One mart sink per table. Targets land in the catalog/schema of the `dbx`
# domain's connection, staged through its Unity Catalog Volume.
@subscriber(
    destination=DatabricksDest(tables=["bookings_enriched"], if_table_exists="replace"),
    input_tables=["airport_marts/bookings_enriched"],
)
def dbx_bookings_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=DatabricksDest(tables=["high_value_bookings"], if_table_exists="replace"),
    input_tables=["airport_marts/high_value_bookings"],
)
def dbx_high_value_bookings(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=DatabricksDest(tables=["flight_roster"], if_table_exists="replace"),
    input_tables=["airport_marts/flight_roster"],
)
def dbx_flight_roster(t: TableFrameSpec) -> TableFrameSpec:
    return t
