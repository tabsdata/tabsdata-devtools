#
# Copyright 2026 Tabsdata Inc.
#

"""caps_db2 — exercise the Db2 connector's config surface (mirror of caps_postgres,
Db2 dialect: FETCH FIRST 10 ROWS ONLY; unquoted identifiers fold to UPPERCASE).

SOURCE (`@publisher`, collection ``db2_in``, reads seeded ``db2_world_xs``):
- ``db2_in`` (base 3 queries), ``db2_in_inc`` (watermark; column is ``ID`` uppercase),
  ``db2_in_none`` (WHERE 1=0), ``db2_in_multiquery`` (2 queries, transactional=False).

DEST (`@subscriber`, collection ``db2_out``, input from datagen ``caps_input/cap_rows``):
- ``db2_out_append`` / ``db2_out_replace`` / ``db2_out_none``.
  NOTE the Db2 dest is known to hit an ibm_db array-bind / SQLRowCount bug (DB2_9 /
  CLI0125E) on write — expect these to stall until the connector is fixed.

``schema_evolution`` (``"strict"`` by default, or ``"update"``) is the
schema-evolution suites'.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``db2_meta_keep`` and
``db2_meta_drop`` (collection ``db2_in``) read the same one-query ``SELECT`` with and
without that ``src_cfg`` key, and one ``@transformer`` each in collection ``db2_meta``
asserts that side: ``db2_meta_keep_check`` that ``@td.sql.query`` and
``@td.sql.initial_values`` are there (none null, and the data columns are exactly the
ones asked for), ``db2_meta_drop_check`` that no ``@td.`` column is left and the data
columns are unchanged. See functions/_srcmeta.py, which also explains why one
transformer over both tables cannot work.
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec, TableFramesSpec,
    TransactionCtx,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.tableframe.functions import concat
from tabsdatak.conn.db2 import Db2Dest, Db2Src

try:
    from ._srcmeta import (
        DROP_METADATA,
        NO_BINDS,
        QUERY_COLUMNS,
        SQL_META,
        SQL_META_INITIAL_VALUES,
        SQL_META_QUERY,
        check_drop,
        check_keep,
    )
except ImportError:
    from _srcmeta import (
        DROP_METADATA,
        NO_BINDS,
        QUERY_COLUMNS,
        SQL_META,
        SQL_META_INITIAL_VALUES,
        SQL_META_QUERY,
        check_drop,
        check_keep,
    )


@publisher(
    source=Db2Src(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["d2_country", "d2_city", "d2_language"],
)
def db2_in(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)


@publisher(
    source=Db2Src(
        queries=["SELECT * FROM city WHERE id > :wm ORDER BY id FETCH FIRST 10 ROWS ONLY"],
        initial_values={"wm": 0},
    ),
    output_tables=["d2_city_inc"],
)
def db2_in_inc(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is not None:
        # Db2 folds unquoted identifiers to UPPERCASE -> the column is `ID`.
        # max_for("ID") returns the top row's columns as {col: value}, None if empty.
        row = city.max_for("ID")
        if row is not None and row["ID"] is not None:
            ctx.set_attr("wm", int(row["ID"]))
    return city


@publisher(
    source=Db2Src(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["d2_none"],
)
def db2_in_none(city: TableFrameSpec) -> TableFrameSpec:
    return None if city is None else city


@publisher(
    source=Db2Src(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        transactional=False,
    ),
    output_tables=["d2_country_slim", "d2_city_slim"],
)
def db2_in_multiquery(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)


@subscriber(
    destination=Db2Dest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def db2_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=Db2Dest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def db2_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=Db2Dest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def db2_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME QUERY differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A SQL source reports
# `@td.sql.query` — the text it ran — and `@td.sql.initial_values` — the binds it ran
# with, `{}` here — unless the key drops them. The query is a module constant so the
# assertion can pin the recorded text to the text this suite asked for.
_META_QUERY = "SELECT code, name FROM country"


@publisher(source=Db2Src(queries=[_META_QUERY]), output_tables=["meta_keep"])
def db2_meta_keep(country: TableFrameSpec) -> TableFrameSpec:
    return country


@publisher(
    source=Db2Src(queries=[_META_QUERY], src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def db2_meta_drop(country: TableFrameSpec) -> TableFrameSpec:
    return country


@transformer(input_tables=["db2_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def db2_meta_keep_check(keep_versions: TableFramesSpec) -> TableFrameSpec:
    keep = concat(keep_versions or [])
    return check_keep(keep, SQL_META, QUERY_COLUMNS,
                      exact={SQL_META_QUERY: _META_QUERY,
                             SQL_META_INITIAL_VALUES: NO_BINDS})


@transformer(input_tables=["db2_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def db2_meta_drop_check(drop_versions: TableFramesSpec) -> TableFrameSpec:
    drop = concat(drop_versions or [])
    return check_drop(drop, QUERY_COLUMNS)
