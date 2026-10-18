#
# Copyright 2026 Tabsdata Inc.
#

"""caps_databricks — Databricks: SQL source modes + bulk dest full matrix
(create/append/replace + SCHEMA EVOLUTION ``update``). Dest needs the staging Volume
from the connection to already exist.

SOURCE (`@publisher`, collection ``databricks_in``, reads seeded ``databricks_world_xs``):
- ``databricks_in`` (base 3 queries), ``databricks_in_inc`` (watermark, LIMIT 10),
  ``databricks_in_none`` (WHERE 1=0).

DEST (`@subscriber`, collection ``databricks_out``, input from datagen):
- ``databricks_out_append`` / ``databricks_out_replace`` / ``databricks_out_none``.
- ``databricks_evolve_v1`` (narrow -> creates cap_evolve) then ``databricks_evolve_v2``
  (wide, ``schema_evolution="update"`` -> mergeSchema adds column). Run v1 then v2.
- ``databricks_merge_<batch>``: ``if_table_exists="merge"`` of the CDC batches in
  ``_merge_plan.py`` onto each batch's target (``cap_merge``, ``cap_merge_from_load``,
  ``cap_merge_from_truncate``) -- changes, initial loads, truncates.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``databricks_meta_keep`` and
``databricks_meta_drop`` (collection ``databricks_in``) read the same one-query
``SELECT`` with and without that ``src_cfg`` key, and one ``@transformer`` each in
collection ``databricks_meta`` asserts that side: ``databricks_meta_keep_check`` that
``@td.sql.query`` and ``@td.sql.initial_values`` are there (none null, and the data
columns are exactly the ones asked for), ``databricks_meta_drop_check`` that no ``@td.``
column is left and the data columns are unchanged. See functions/_srcmeta.py, which also
explains why one transformer over both tables cannot work.
"""
from __future__ import annotations

from tabsdatak.api import (
    TableFrameSpec,
    TransactionCtx,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.databricks import DatabricksDest, DatabricksSrc, MergeCfg

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


# --- SOURCE (existing databricks_world_xs data) -----------------------------
@publisher(
    source=DatabricksSrc(
        queries=[
            "SELECT * FROM country",
            "SELECT * FROM city",
            "SELECT * FROM country_language",
        ],
    ),
    output_tables=["db_country", "db_city", "db_language"],
)
def databricks_in(
    country: TableFrameSpec,
    city: TableFrameSpec,
    language: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]:
    return (country, city, language)


@publisher(
    source=DatabricksSrc(
        # `:wm` binds natively as a typed statement parameter (no text
        # interpolation) — same convention as the other SQL sources. LIMIT 10
        # is Spark SQL.
        queries=["SELECT * FROM city WHERE id > :wm ORDER BY id LIMIT 10"],
        initial_values={"wm": 0},
    ),
    output_tables=["db_city_inc"],
)
def databricks_in_inc(city: TableFrameSpec, ctx: TransactionCtx) -> TableFrameSpec:
    if city is not None:
        # max_for("id") returns the top row's columns as {col: value}, None if empty.
        row = city.max_for("id")
        if row is not None and row["id"] is not None:
            ctx.set_attr("wm", int(row["id"]))
    return city


@publisher(
    source=DatabricksSrc(queries=["SELECT * FROM city WHERE 1 = 0"]),
    output_tables=["db_none"],
)
def databricks_in_none(city: TableFrameSpec) -> TableFrameSpec:
    return None if city is None else city


# --- DEST (input from datagen caps_input) ------------------------------------
@subscriber(
    destination=DatabricksDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def databricks_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=DatabricksDest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def databricks_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=DatabricksDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def databricks_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


@subscriber(
    destination=DatabricksDest(tables=["cap_evolve"], if_table_exists="replace"),
    input_tables=["caps_input/cap_evo_v1"],
)
def databricks_evolve_v1(v1: TableFrameSpec) -> TableFrameSpec:
    return v1


@subscriber(
    destination=DatabricksDest(
        tables=["cap_evolve"],
        if_table_exists="append",
        schema_evolution="update",
    ),
    input_tables=["caps_input/cap_evo_v2"],
)
def databricks_evolve_v2(v2: TableFrameSpec) -> TableFrameSpec:
    return v2


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME QUERY differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A SQL source reports
# `@td.sql.query` — the text it ran — and `@td.sql.initial_values` — the binds it ran
# with, `{}` here — unless the key drops them. The query is a module constant so the
# assertion can pin the recorded text to the text this suite asked for.
_META_QUERY = "SELECT code, name FROM country"


@publisher(source=DatabricksSrc(queries=[_META_QUERY]), output_tables=["meta_keep"])
def databricks_meta_keep(country: TableFrameSpec) -> TableFrameSpec:
    return country


@publisher(
    source=DatabricksSrc(queries=[_META_QUERY], src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def databricks_meta_drop(country: TableFrameSpec) -> TableFrameSpec:
    return country


@transformer(input_tables=["databricks_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def databricks_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, SQL_META, QUERY_COLUMNS,
                      exact={SQL_META_QUERY: _META_QUERY,
                             SQL_META_INITIAL_VALUES: NO_BINDS})


@transformer(input_tables=["databricks_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def databricks_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, QUERY_COLUMNS)


# --- MERGE (`if_table_exists="merge"`) -------------------------------------
# One subscriber per batch of _merge_plan.py onto the batch's target, keyed on
# `cap_id` with the CDC marker in `op`; the suite triggers the batches in order
# and checks the target after each (scripts/verify_merge.py).
def _merge_dest(table: str) -> DatabricksDest:
    return DatabricksDest(
        tables=[table],
        if_table_exists="merge",
        merge_cfg=[MergeCfg(on=["cap_id"], op_column="op")],
    )


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b1"],
)
def databricks_merge_b1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b2"],
)
def databricks_merge_b2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b3"],
)
def databricks_merge_b3(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b4"],
)
def databricks_merge_b4(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b5"],
)
def databricks_merge_b5(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b6"],
)
def databricks_merge_b6(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b7"],
)
def databricks_merge_b7(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b8"],
)
def databricks_merge_b8(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_load"),
    input_tables=["caps_input/cap_merge_load1"],
)
def databricks_merge_load1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_load"),
    input_tables=["caps_input/cap_merge_load2"],
)
def databricks_merge_load2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_truncate"),
    input_tables=["caps_input/cap_merge_trunc1"],
)
def databricks_merge_trunc1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_truncate"),
    input_tables=["caps_input/cap_merge_trunc2"],
)
def databricks_merge_trunc2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
