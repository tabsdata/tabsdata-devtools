#
# Copyright 2026 Tabsdata Inc.
#

"""caps_snowflake — Snowflake bulk dest write modes (create/append/replace/merge;
``schema_evolution`` is the schema-evolution suites'). Input from the dev datagen
``caps_input/cap_rows`` frame.

- ``snowflake_out_append``  : ``if_table_exists="append"`` — create then accumulate.
- ``snowflake_out_replace`` : ``if_table_exists="replace"`` — create then TRUNCATE+reload.
- ``snowflake_out_none``    : return-None contract.
- ``snowflake_merge_<batch>`` : ``if_table_exists="merge"`` of the CDC batches in
  ``_merge_plan.py`` onto each batch's target (``cap_merge``, ``cap_merge_from_load``,
  ``cap_merge_from_truncate``; the connector quotes a table name as written, so
  these are lower case in Snowflake) -- changes, initial loads, truncates. The engine
  is left unset: its default, ``iceberg``, is the one a merge takes (it refuses
  ``native``).
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest, MergeCfg


@subscriber(
    destination=SnowflakeDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def snowflake_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=SnowflakeDest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def snowflake_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=SnowflakeDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def snowflake_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# --- MERGE (`if_table_exists="merge"`) -------------------------------------
# One subscriber per batch of _merge_plan.py onto the batch's target, keyed on
# `cap_id` with the CDC marker in `op`; the suite triggers the batches in order
# and checks the target after each (scripts/verify_merge.py).
def _merge_dest(table: str) -> SnowflakeDest:
    return SnowflakeDest(
        tables=[table],
        if_table_exists="merge",
        merge_cfg=[MergeCfg(on=["cap_id"], op_column="op")],
    )


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b1"],
)
def snowflake_merge_b1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b2"],
)
def snowflake_merge_b2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b3"],
)
def snowflake_merge_b3(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b4"],
)
def snowflake_merge_b4(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b5"],
)
def snowflake_merge_b5(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b6"],
)
def snowflake_merge_b6(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b7"],
)
def snowflake_merge_b7(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge"),
    input_tables=["caps_input/cap_merge_b8"],
)
def snowflake_merge_b8(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_load"),
    input_tables=["caps_input/cap_merge_load1"],
)
def snowflake_merge_load1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_load"),
    input_tables=["caps_input/cap_merge_load2"],
)
def snowflake_merge_load2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_truncate"),
    input_tables=["caps_input/cap_merge_trunc1"],
)
def snowflake_merge_trunc1(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=_merge_dest("cap_merge_from_truncate"),
    input_tables=["caps_input/cap_merge_trunc2"],
)
def snowflake_merge_trunc2(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
