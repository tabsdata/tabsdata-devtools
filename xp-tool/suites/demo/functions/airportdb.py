#
# Copyright 2026 Tabsdata Inc.
#

"""demo · airportdb — airline operations over the `airportdb` sample in PostgreSQL.

Three stages, one collection each:

  airport_src   (@publisher)    one transactional PostgresSrc read of flight /
                                booking / passenger / airline / airport /
                                airport_geo (six queries, 100 rows each, ONE
                                consistent snapshot), on a 5-minute cron
  airport_marts (@transformer)  enrich bookings and flights, filter high-value
                                bookings, join the airport directory
  airport_s3    (@subscriber)   write each mart to a parquet object in S3

The marts use the Tabsdata TableFrame API only (join / filter / select / sort /
rename) — no polars. They are ROW-PRESERVING transforms (they carry the
framework's system columns through), which is what a @transformer output must be
to sink cleanly. The domain is seeded at `data: l` (`create-data --size 1000`,
~100k bookings / 5k flights / 5k passengers), so the joins are not toy-sized.
"""
from __future__ import annotations

from tabsdatak.api import CronTrigger, TableFrameSpec, publisher, subscriber, transformer
from tabsdatak.conn.postgres import PostgresSrc
from tabsdatak.conn.s3 import S3Dest
from tabsdatak.tableframe.functions import col


# --- ingest: PostgreSQL airportdb -> airport_src ------------------------------
# Unqualified names resolve against the domain's own schema (the connection's
# search path), so the queries read exactly as they would in psql. `transactional`
# defaults to True: all six run in one session and see one snapshot. Every query
# is capped at 100 rows (ordered by key, so the cap is deterministic): the point
# of this publisher is the pipeline, not the volume.
#
# SCHEDULED: `trigger_by=CronTrigger` fires it every 5 minutes on its own (UTC,
# minute 0 of each 5 — the finance publisher takes minute 2, so the two demo SQL
# publishers never tick in the same minute). The suite's manual trigger coexists
# with the schedule, so `run-project` still produces a first batch immediately.
@publisher(
    source=PostgresSrc(
        queries=[
            "SELECT * FROM flight ORDER BY flight_id LIMIT 100",
            "SELECT * FROM booking ORDER BY booking_id LIMIT 100",
            "SELECT * FROM passenger ORDER BY passenger_id LIMIT 100",
            "SELECT * FROM airline ORDER BY airline_id LIMIT 100",
            "SELECT * FROM airport ORDER BY airport_id LIMIT 100",
            "SELECT * FROM airport_geo ORDER BY airport_id LIMIT 100",
        ],
    ),
    output_tables=["flight", "booking", "passenger", "airline", "airport", "airport_geo"],
    trigger_by=CronTrigger(mask="0-59/5 * * * *"),
)
def pub_airportdb(
    flight: TableFrameSpec,
    booking: TableFrameSpec,
    passenger: TableFrameSpec,
    airline: TableFrameSpec,
    airport: TableFrameSpec,
    airport_geo: TableFrameSpec,
) -> tuple[
    TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec
]:
    return (flight, booking, passenger, airline, airport, airport_geo)


# --- marts: enrichment joins + filters (airport_src -> airport_marts) ---------
@transformer(
    input_tables=[
        "airport_src/booking@HEAD",
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
    # booking -> passenger (who) -> flight (which flight, when) -> airline (carrier).
    enriched = booking.join(
        passenger.select("passenger_id", "passportno", "firstname", "lastname"),
        on="passenger_id",
        how="left",
    )
    enriched = enriched.join(
        flight.select("flight_id", "flightno", "departure", "airline_id"),
        on="flight_id",
        how="left",
    )
    enriched = enriched.join(
        airline.select("airline_id", "airline_name"), on="airline_id", how="left"
    )
    return enriched.select(
        "booking_id",
        "passportno",
        "firstname",
        "lastname",
        "flightno",
        "airline_name",
        "departure",
        "seat",
        "price",
    )


@transformer(input_tables=["airport_src/booking@HEAD"], output_tables=["high_value_bookings"])
def tfr_high_value_bookings(booking: TableFrameSpec) -> TableFrameSpec:
    # Bookings above a price threshold, most expensive first.
    return (
        booking.filter(col("price") > 500)
        .select("booking_id", "flight_id", "passenger_id", "seat", "price")
        .sort("price", descending=True)
    )


@transformer(
    input_tables=[
        "airport_src/flight@HEAD",
        "airport_src/airline@HEAD",
        "airport_src/airport@HEAD",
    ],
    output_tables=["flight_roster"],
)
def tfr_flight_roster(
    flight: TableFrameSpec, airline: TableFrameSpec, airport: TableFrameSpec
) -> TableFrameSpec:
    # Flights with their carrier's name and both endpoints' IATA codes. The airport
    # table is joined TWICE (origin, destination), so each side is renamed first —
    # otherwise the second join would suffix the colliding columns `_right`.
    origin = airport.select("airport_id", "iata", "name").rename(
        {"iata": "from_iata", "name": "from_airport_name"}
    )
    destination = airport.select("airport_id", "iata", "name").rename(
        {"iata": "to_iata", "name": "to_airport_name"}
    )
    roster = flight.join(
        airline.select("airline_id", "airline_name"), on="airline_id", how="left"
    )
    roster = roster.join(origin, left_on="from_airport", right_on="airport_id", how="left")
    roster = roster.join(destination, left_on="to_airport", right_on="airport_id", how="left")
    return roster.select(
        "flight_id",
        "flightno",
        "airline_name",
        "from_iata",
        "from_airport_name",
        "to_iata",
        "to_airport_name",
        "departure",
        "arrival",
    ).sort("departure")


@transformer(
    input_tables=["airport_src/airport@HEAD", "airport_src/airport_geo@HEAD"],
    output_tables=["airport_directory"],
)
def tfr_airport_directory(airport: TableFrameSpec, airport_geo: TableFrameSpec) -> TableFrameSpec:
    # One row per airport: codes + where it is. `airport_geo` repeats `name`, so it is
    # dropped from the right side before the 1:1 join.
    return airport.join(
        airport_geo.select("airport_id", "city", "country", "latitude", "longitude"),
        on="airport_id",
        how="left",
    ).select("airport_id", "iata", "icao", "name", "city", "country", "latitude", "longitude")


# --- serve: one parquet object per mart (airport_marts -> S3) ---------------
# Paths are relative to the s3 domain's base path; every run of a mart overwrites
# its object, so the bucket always holds the latest view.
@subscriber(
    destination=S3Dest(paths=["airportdb/bookings_enriched.parquet"]),
    input_tables=["airport_marts/bookings_enriched"],
)
def sink_bookings_enriched(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["airportdb/high_value_bookings.parquet"]),
    input_tables=["airport_marts/high_value_bookings"],
)
def sink_high_value_bookings(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["airportdb/flight_roster.parquet"]),
    input_tables=["airport_marts/flight_roster"],
)
def sink_flight_roster(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["airportdb/airport_directory.parquet"]),
    input_tables=["airport_marts/airport_directory"],
)
def sink_airport_directory(t: TableFrameSpec) -> TableFrameSpec:
    return t
