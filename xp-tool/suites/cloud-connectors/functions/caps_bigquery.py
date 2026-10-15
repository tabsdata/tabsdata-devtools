#
# Copyright 2026 Tabsdata Inc.
#

"""caps_bigquery — BigQuery bulk dest full matrix: create/append/replace + SCHEMA
EVOLUTION (``update``). Input from dev datagen ``caps_input``.

Target names MUST be backtick-quoted (resolve to project.dataset.table from the conn).

- ``bigquery_out_append``  / ``bigquery_out_replace`` / ``bigquery_out_none``.
- ``bigquery_evolve_v1`` : narrow ``cap_evo_v1`` -> creates ``cap_evolve``.
- ``bigquery_evolve_v2`` : wide ``cap_evo_v2`` appended with ``schema_evolution="update"``
  (ALLOW_FIELD_ADDITION) -> adds the ``population`` column. Run v1 then v2 (v2 not
  auto-triggered so they don't race).
- ``bigquery_merge_<batch>`` : ``if_table_exists="merge"`` of the CDC batches in
  ``_merge_plan.py`` onto each batch's target (``cap_merge``, ``cap_merge_from_load``,
  ``cap_merge_from_truncate``) -- changes, initial loads, truncates. A merge requires
  ``bigquery.schema_evolution_engine="iceberg"``.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest, MergeCfg


@subscriber(
    destination=BigQueryDest(tables=["`cap_append`"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def bigquery_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=BigQueryDest(tables=["`cap_replace`"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def bigquery_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=BigQueryDest(tables=["`cap_append`"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def bigquery_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


@subscriber(
    destination=BigQueryDest(tables=["`cap_evolve`"], if_table_exists="replace"),
    input_tables=["caps_input/cap_evo_v1"],
)
def bigquery_evolve_v1(v1: TableFrameSpec) -> TableFrameSpec:
    return v1


@subscriber(
    destination=BigQueryDest(
        tables=["`cap_evolve`"],
        if_table_exists="append",
        schema_evolution="update",
    ),
    input_tables=["caps_input/cap_evo_v2"],
)
def bigquery_evolve_v2(v2: TableFrameSpec) -> TableFrameSpec:
    return v2


# --- MERGE (`if_table_exists="merge"`) -------------------------------------
# One subscriber per batch of _merge_plan.py onto the batch's target, keyed on
# `cap_id` with the CDC marker in `op`; the suite triggers the batches in order
# and checks the target after each (scripts/verify_merge.py).
def _merge_dest(table: str) -> BigQueryDest:
    return BigQueryDest(
        tables=[table],
        if_table_exists="merge",
        merge_cfg=[MergeCfg(on=["cap_id"], op_column="op")],
        dest_cfg={"bigquery.schema_evolution_engine": "iceberg"},
    )


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b1"],
)
def bigquery_merge_b1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b2"],
)
def bigquery_merge_b2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b3"],
)
def bigquery_merge_b3(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b4"],
)
def bigquery_merge_b4(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b5"],
)
def bigquery_merge_b5(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b6"],
)
def bigquery_merge_b6(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b7"],
)
def bigquery_merge_b7(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge`"),
    input_tables=["caps_input/cap_merge_b8"],
)
def bigquery_merge_b8(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge_from_load`"),
    input_tables=["caps_input/cap_merge_load1"],
)
def bigquery_merge_load1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge_from_load`"),
    input_tables=["caps_input/cap_merge_load2"],
)
def bigquery_merge_load2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge_from_truncate`"),
    input_tables=["caps_input/cap_merge_trunc1"],
)
def bigquery_merge_trunc1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("`cap_merge_from_truncate`"),
    input_tables=["caps_input/cap_merge_trunc2"],
)
def bigquery_merge_trunc2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
