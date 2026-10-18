#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mysql — exercise the MySQL connector's config surface (mirror of caps_postgres,
MySQL dialect).

SOURCE (`@publisher`, collection ``mysql_in``, reads the seeded ``mysql_world_xs`` domain):
- ``mysql_in``            : base, three ``SELECT *`` queries -> three slots.
- ``mysql_in_inc``        : incremental watermark (``id > :wm`` + ``ctx.set_attr``, ``LIMIT 10``).
- ``mysql_in_none``       : ``WHERE 1=0`` -> empty single-mode slot -> publish None.
- ``mysql_in_multiquery`` : two queries -> two slots, ``transactional=False``.

DEST (`@subscriber`, collection ``mysql_out``, input from datagen ``caps_input/cap_rows``):
- ``mysql_out_append``  : ``if_table_exists="append"`` — create then accumulate.
- ``mysql_out_replace`` : ``if_table_exists="replace"`` — create then DROP+recreate.
- ``mysql_out_none``    : return-None contract.

MySQL has no ``schema_evolution`` (append/replace only). Append and replace target
DIFFERENT tables so both fire off the same ``cap_rows`` publish.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``mysql_meta_keep`` and
``mysql_meta_drop`` (collection ``mysql_in``) read the same one-query ``SELECT`` with
and without that ``src_cfg`` key, and one ``@transformer`` each in collection
``mysql_meta`` asserts that side: ``mysql_meta_keep_check`` that ``@td.sql.query`` and
``@td.sql.initial_values`` are there (none null, and the data columns are exactly the
ones asked for), ``mysql_meta_drop_check`` that no ``@td.`` column is left and the data
columns are unchanged. See functions/_srcmeta.py, which also explains why one
transformer over both tables cannot work.
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    TransactionCtx,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.mysql import MySQLDest, MySQLSrc

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


# --- SOURCE variants (existing mysql_world_xs data) --------------------------
@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["my_country", "my_city", "my_language"],
)
def mysql_in(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)


@publisher(
    source=MySQLSrc(
        queries=["SELECT * FROM city WHERE id > :wm ORDER BY id LIMIT 10"],
        initial_values={"wm": 0},
    ),
    output_tables=["my_city_inc"],
)
def mysql_in_inc(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is not None:
        # max_for("id") returns the top row's columns as {col: value}, None if empty.
        row = city.max_for("id")
        if row is not None and row["id"] is not None:
            ctx.set_attr("wm", int(row["id"]))
    return city


@publisher(
    source=MySQLSrc(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["my_none"],
)
def mysql_in_none(city: TableFrameSpec) -> TableFrameSpec:
    return None if city is None else city


@publisher(
    source=MySQLSrc(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        transactional=False,
    ),
    output_tables=["my_country_slim", "my_city_slim"],
)
def mysql_in_multiquery(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)


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
# assertion can pin the recorded text to the text this suite asked for.
_META_QUERY = "SELECT code, name FROM country"


@publisher(source=MySQLSrc(queries=[_META_QUERY]), output_tables=["meta_keep"])
def mysql_meta_keep(country: TableFrameSpec) -> TableFrameSpec:
    return country


@publisher(
    source=MySQLSrc(queries=[_META_QUERY], src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def mysql_meta_drop(country: TableFrameSpec) -> TableFrameSpec:
    return country


@transformer(input_tables=["mysql_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def mysql_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, SQL_META, QUERY_COLUMNS,
                      exact={SQL_META_QUERY: _META_QUERY,
                             SQL_META_INITIAL_VALUES: NO_BINDS})


@transformer(input_tables=["mysql_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def mysql_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, QUERY_COLUMNS)
