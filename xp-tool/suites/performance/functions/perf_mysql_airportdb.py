#
# Copyright 2026 Tabsdata Inc.
#

"""perf_mysql_airportdb — container-connectors' caps_mysql surface over the airportdb
model, at a scale where one ingested table has more than 100K rows.

SOURCE (`@publisher`, collection ``mysql_in``, reads the seeded ``mysql_airportdb_l`` domain;
size l -> ``booking`` 100,000 rows, ``flight`` 5,000, ``airline`` 50):
- ``mysql_in``            : base, three ``SELECT *`` queries -> three slots; ``booking`` is
                            read twice with ``UNION ALL`` -> one 200,000-row table.
- ``mysql_in_inc``        : incremental watermark (``booking_id > :wm`` + ``ctx.set_attr``,
                            ``LIMIT 10``).
- ``mysql_in_none``       : ``WHERE 1=0`` -> empty single-mode slot -> publish None.
- ``mysql_in_multiquery`` : two queries -> two slots, ``transactional=False``.

DEST (`@subscriber`, collection ``mysql_out``, input from datagen ``caps_input/cap_rows``):
unchanged from caps_mysql — ``mysql_out_append``, ``mysql_out_replace``, ``mysql_out_none``.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract, as in caps_mysql, over
``airline`` with its columns aliased to the ``code``/``name`` pair functions/_srcmeta.py
asserts (``QUERY_COLUMNS``), so the shared checks hold unchanged.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TrxCtx, publisher, subscriber, transformer
from tabsdatak.conn.mysql import MySQLDest, MySQLSrc

try:
    from ._srcmeta import (
        DROP_METADATA, NO_BINDS, QUERY_COLUMNS, SQL_META,
        SQL_META_INITIAL_VALUES, SQL_META_QUERY, check_drop, check_keep,
    )
except ImportError:
    from _srcmeta import (
        DROP_METADATA, NO_BINDS, QUERY_COLUMNS, SQL_META,
        SQL_META_INITIAL_VALUES, SQL_META_QUERY, check_drop, check_keep,
    )


# --- SOURCE variants (existing mysql_airportdb_l data) -----------------------
@publisher(
    source=MySQLSrc(
        queries=[
            # Size l seeds exactly 100,000 bookings; reading them twice crosses 100K
            # rows in one table without a join (booking_id repeats, once per copy).
            "SELECT * FROM booking UNION ALL SELECT * FROM booking",
            "SELECT * FROM flight",
            "SELECT * FROM airline",
        ],
    ),
    output_tables=["my_booking", "my_flight", "my_airline"],
)
def mysql_in(
    booking: TableFrameSpec,
    flight: TableFrameSpec,
    airline: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (booking, flight, airline)


@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT * FROM booking WHERE booking_id > :wm ORDER BY booking_id LIMIT 10"
        ],
        initial_values={"wm": 0},
    ),
    output_tables=["my_booking_inc"],
)
def mysql_in_inc(booking: TableFrameSpec, ctx: TrxCtx) -> TableFrameSpec:
    if booking is not None:
        # max_for() returns the top row's columns as {col: value}, None if empty.
        row = booking.max_for("booking_id")
        if row is not None and row["booking_id"] is not None:
            ctx.set_attr("wm", int(row["booking_id"]))
    return booking


@publisher(
    source=MySQLSrc(queries=["SELECT * FROM booking WHERE 1 = 0"]),
    output_tables=["my_none"],
)
def mysql_in_none(booking: TableFrameSpec) -> TableFrameSpec:
    return None if booking is None else booking


@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT airline_id, iata, airline_name FROM airline",
            "SELECT flight_id, flightno, airline_id FROM flight",
        ],
        transactional=False,
    ),
    output_tables=["my_airline_slim", "my_flight_slim"],
)
def mysql_in_multiquery(
    airline: TableFrameSpec,
    flight: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (airline, flight)


# --- DEST variants (input from datagen caps_input/cap_rows) -------------------
@subscriber(
    destination=MySQLDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def mysql_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MySQLDest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def mysql_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MySQLDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def mysql_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME QUERY differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A SQL source reports
# `@td.sql.query` — the text it ran — and `@td.sql.initial_values` — the binds it ran
# with, `{}` here — unless the key drops them. The query is a module constant so the
# assertion can pin the recorded text to the text this suite asked for; the aliases give
# the data columns _srcmeta's QUERY_COLUMNS names.
_META_QUERY = "SELECT iata AS code, airline_name AS name FROM airline"


@publisher(source=MySQLSrc(queries=[_META_QUERY]), output_tables=["meta_keep"])
def mysql_meta_keep(airline: TableFrameSpec) -> TableFrameSpec:
    return airline


@publisher(
    source=MySQLSrc(queries=[_META_QUERY], src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def mysql_meta_drop(airline: TableFrameSpec) -> TableFrameSpec:
    return airline


@transformer(input_tables=["mysql_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def mysql_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, SQL_META, QUERY_COLUMNS,
                      exact={SQL_META_QUERY: _META_QUERY,
                             SQL_META_INITIAL_VALUES: NO_BINDS})


@transformer(input_tables=["mysql_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def mysql_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, QUERY_COLUMNS)
