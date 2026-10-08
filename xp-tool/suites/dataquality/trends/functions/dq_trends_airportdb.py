#
# Copyright 2026 Tabsdata Inc.
#

"""dq_trends_airportdb — data-quality summaries and their trends over a MySQL CDC stream.

Two functions:

- ``airportdb_cdc`` (collection ``dq_trends_cdc``): a ``MySQLCdcStreamSrc`` over the
  ``airportdb`` tables ``modify-data`` changes -- ``airport`` (inserts, updates),
  ``passenger`` (inserts, updates), ``booking`` (deletes) -- and ``xp_sentinel``,
  started with ``initial_load=True``: each table's rows first, as inserts behind a LOAD
  control row, then the binlog from the position the load is consistent at. It triggers
  once a minute: ``batch_min_secs=60`` and ``batch_max_secs=60`` stage a batch exactly a
  minute after the previous one while changes wait, and with no ``batch_idle_secs`` no
  empty batch is staged -- every version carries CDC changes, and the suite changes the
  tables every minute, so the trend's run tier gets a point a minute.
- ``dq_airportdb`` (collection ``dq_trends_ops``): passes the ``airport`` and
  ``passenger`` change tables through and carries a ``DataQuality`` action on each,
  three boolean classifiers and a ``Summary`` with a ``SummaryTrend``. Every version it
  writes adds a ``<table>_dq_summary`` version, and the server's trend child function
  (registered with this one) folds that into ``<table>_dq_summary_trends``.

Six classifiers, each moving on every run: what ``modify-data`` inserts into airportdb
carries six defects, each at a share the run's seed sets (5-60%, a few points or more
apart from the previous run's -- the model's ``_defect_rate``), one per classifier. The
seed data passes them all, as do the update values; a LOAD row's data columns are null.
A pattern is one Python's ``re`` (the API validates with it) and polars (the engine runs
it) both read, so no ``\p{Lu}``:

  airport    IsNotNull(iata)                    iata left NULL
             Matches(iata, ^[A-Z]{3}$)          iata in lower case (a NULL is neither)
             Matches(name, ^[A-ZÀ-ÖØ-Þ])        name in lower case
  passenger  Matches(passportno, ^[A-Z][0-9]{8}$)   passport C<7 digits>X
             Matches(firstname, ^[A-ZÀ-ÖØ-Þ])   firstname in lower case
             Matches(lastname, ^[A-ZÀ-ÖØ-Þ])    lastname in lower case

``booking`` is tracked by the stream (a delete a minute) and classified by nothing: one
row a minute is 0% or 100%, which cannot move every run. The CDC tables' data columns
keep the source's names; the ``@td.cdc.*`` columns are left alone.

The DataQuality step lives on a transformer rather than on the stream publisher: it is
the path every other ``dataquality`` suite tests, so a failure here is the trend's.
"""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher, transformer
from tabsdatak.conn.mysql import MySQLCdcStreamSrc
from tabsdatak.dataquality import DataQuality, IsNotNull, Matches, Summary, SummaryTrend
from tabsdatak.tableframe.functions import concat

CDC = "dq_trends_cdc"

# Unqualified: MySQL resolves them against the connection's database, the domain's.
_TABLES = ["airport", "passenger", "booking"]
# The tables classified: booking's one delete a minute could not move every run.
_CHECKED = ["airport", "passenger"]
_SENTINEL_TABLE = "xp_sentinel"

# The batch limits are the decorator's (a minute, the floor, so no unsafe_seconds).
# Buffers flush well inside the minute, so a minute's changes are in its version
# rather than the next one's.
_CFG = {
    "tabsdata.cdc.buffer.max_secs": 10,
    "tabsdata.cdc.poll.idle_secs": 1,
    "tabsdata.cdc.poll.max_secs": 5,
}

# The defaults, spelled out: the run tier keeps every point of a 30-minute run, and
# its week and month buckets fold them from the first.
_TREND = SummaryTrend(days=7, weeks=12, months=24)


def _summary() -> Summary:
    return Summary(trend=_TREND)


# An upper-case first letter, Latin-1 included (the seed's Müller, Óscar).
_CAPITALISED = "^[A-ZÀ-ÖØ-Þ]"

AIRPORT_DQ = DataQuality(
    table="airport",
    classifiers=[
        IsNotNull(["iata"]),
        Matches(["iata"], pattern="^[A-Z]{3}$"),
        Matches(["name"], pattern=_CAPITALISED),
    ],
    operators=[_summary()],
)
PASSENGER_DQ = DataQuality(
    table="passenger",
    classifiers=[
        Matches(["passportno"], pattern="^[A-Z][0-9]{8}$"),
        Matches(["firstname", "lastname"], pattern=_CAPITALISED),
    ],
    operators=[_summary()],
)


@stream_publisher(
    source=MySQLCdcStreamSrc(
        tables=[*_TABLES, _SENTINEL_TABLE],
        initial_load=True,
        src_cfg=_CFG,
    ),
    batch_min_secs=60,
    batch_max_secs=60,
    output_tables=[f"{t}_changes" for t in [*_TABLES, _SENTINEL_TABLE]],
)
def airportdb_cdc(
    airport: TableFramesSpec,
    passenger: TableFramesSpec,
    booking: TableFramesSpec,
    xp_sentinel: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    # Each slot is the frames this flush carried for its table; `concat` is None for
    # none, and a table with nothing this minute gets no data in its version.
    return concat(airport), concat(passenger), concat(booking), concat(xp_sentinel)


@transformer(
    input_tables=[f"{CDC}/{t}_changes" for t in _CHECKED],
    output_tables=_CHECKED,
    on_tables=[AIRPORT_DQ, PASSENGER_DQ],
)
def dq_airportdb(
    airport: TableFrameSpec,
    passenger: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return airport, passenger
