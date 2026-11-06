#
# Copyright 2026 Tabsdata Inc.
#

"""caps_mssql — exercise the SQL Server connector's config surface (mirror of
caps_postgres, T-SQL dialect).

SOURCE (`@publisher`, collection ``mssql_in``, reads the seeded ``mssqlserver_world_xs``):
- ``mssql_in``            : base, three ``SELECT *`` queries -> three slots.
- ``mssql_in_inc``        : incremental watermark; SQL Server has no LIMIT, so it uses the
                            ANSI ``OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY`` (requires ORDER BY).
- ``mssql_in_none``       : ``WHERE 1=0`` -> empty single-mode slot -> publish None.
- ``mssql_in_multiquery`` : two queries -> two slots, ``transactional=False``.

DEST (`@subscriber`, collection ``mssql_out``, input from datagen ``caps_input/cap_rows``):
- ``mssql_out_append``  / ``mssql_out_replace`` / ``mssql_out_none``.

``schema_evolution`` (``"strict"`` by default, or ``"update"``) is the
schema-evolution suites'.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``mssql_meta_keep`` and
``mssql_meta_drop`` (collection ``mssql_in``) read the same one-query ``SELECT`` with
and without that ``src_cfg`` key, and one ``@transformer`` each in collection
``mssql_meta`` asserts that side: ``mssql_meta_keep_check`` that ``@td.sql.query`` and
``@td.sql.initial_values`` are there (none null, and the data columns are exactly the
ones asked for), ``mssql_meta_drop_check`` that no ``@td.`` column is left and the data
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
from tabsdatak.conn.mssql import MSSQLDest, MSSQLSrc

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


# --- SOURCE variants (existing mssqlserver_world_xs data) --------------------
@publisher(
    source=MSSQLSrc(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["ms_country", "ms_city", "ms_language"],
)
def mssql_in(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)


@publisher(
    source=MSSQLSrc(
        queries=[
            "SELECT * FROM city WHERE id > :wm ORDER BY id "
            "OFFSET 0 ROWS FETCH NEXT 10 ROWS ONLY"
        ],
        initial_values={"wm": 0},
    ),
    output_tables=["ms_city_inc"],
)
def mssql_in_inc(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is not None:
        # max_for("id") returns the top row's columns as {col: value}, None if empty.
        row = city.max_for("id")
        if row is not None and row["id"] is not None:
            ctx.set_attr("wm", int(row["id"]))
    return city


@publisher(
    source=MSSQLSrc(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["ms_none"],
)
def mssql_in_none(city: TableFrameSpec) -> TableFrameSpec:
    return None if city is None else city


@publisher(
    source=MSSQLSrc(
        queries=[
            "SELECT code, name FROM country",
            "SELECT id, name FROM city",
        ],
        transactional=False,
    ),
    output_tables=["ms_country_slim", "ms_city_slim"],
)
def mssql_in_multiquery(
    country: TableFrameSpec,
    city: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return (country, city)


# --- DEST variants (input from datagen caps_input/cap_rows) -------------------
@subscriber(
    destination=MSSQLDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def mssql_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MSSQLDest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def mssql_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=MSSQLDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def mssql_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME QUERY differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A SQL source reports
# `@td.sql.query` — the text it ran — and `@td.sql.initial_values` — the binds it ran
# with, `{}` here — unless the key drops them. The query is a module constant so the
# assertion can pin the recorded text to the text this suite asked for.
_META_QUERY = "SELECT code, name FROM country"


@publisher(source=MSSQLSrc(queries=[_META_QUERY]), output_tables=["meta_keep"])
def mssql_meta_keep(country: TableFrameSpec) -> TableFrameSpec:
    return country


@publisher(
    source=MSSQLSrc(queries=[_META_QUERY], src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def mssql_meta_drop(country: TableFrameSpec) -> TableFrameSpec:
    return country


@transformer(input_tables=["mssql_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def mssql_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, SQL_META, QUERY_COLUMNS,
                      exact={SQL_META_QUERY: _META_QUERY,
                             SQL_META_INITIAL_VALUES: NO_BINDS})


@transformer(input_tables=["mssql_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def mssql_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, QUERY_COLUMNS)
