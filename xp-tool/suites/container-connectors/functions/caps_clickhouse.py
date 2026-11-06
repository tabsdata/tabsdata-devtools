#
# Copyright 2026 Tabsdata Inc.
#

"""caps_clickhouse — exercise the ClickHouse bulk connector's full write-mode matrix:
create-on-write, append, replace, and SCHEMA EVOLUTION. Azure Blob staging (via the
clickhouse_bulk_out_az connection — no S3 grant needed). Input comes from the dev
datagen ``caps_input`` collection so the data is controlled.

DEST variants (`@subscriber`, collection ``clickhouse_out``):
- ``clickhouse_out_append``  : ``if_table_exists="append"`` — first run CREATES cap_append,
                               re-running ACCUMULATES.
- ``clickhouse_out_replace`` : ``if_table_exists="replace"`` — first run creates cap_replace,
                               re-running DROP+recreates (row count stays).
- ``clickhouse_out_none``    : return-None contract (write_out not invoked).

SCHEMA EVOLUTION (two functions writing the SAME table ``cap_evolve``, run in order):
- ``clickhouse_evolve_v1`` : writes the NARROW ``cap_evo_v1`` (code, name) with
                             ``replace`` -> creates cap_evolve with the narrow schema.
- ``clickhouse_evolve_v2`` : writes the WIDE ``cap_evo_v2`` (code, name, population) with
                             ``append`` + ``schema_evolution="update"`` -> the connector
                             ALTERs cap_evolve to add the new ``population`` column
                             (``"strict"``, the default, refuses the batch).
  ORDER MATTERS: run v1 (trigger caps_evo_v1) and let it commit, THEN run v2 (trigger
  caps_evo_v2). v2 is not auto-triggered so the two don't race on cap_evolve.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.clickhouse import ClickHouseDest


# --- write modes (input: datagen caps_input/cap_rows) ------------------------
@subscriber(
    destination=ClickHouseDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def clickhouse_out_append(rows: TableFrameSpec) -> TableFrameSpec:
    # First run CREATES cap_append; each re-run APPENDS (count grows).
    return rows


@subscriber(
    destination=ClickHouseDest(tables=["cap_replace"], if_table_exists="replace"),
    input_tables=["caps_input/cap_rows"],
)
def clickhouse_out_replace(rows: TableFrameSpec) -> TableFrameSpec:
    # First run creates cap_replace; each re-run DROP+recreates (count stays).
    return rows


@subscriber(
    destination=ClickHouseDest(tables=["cap_append"], if_table_exists="append"),
    input_tables=["caps_input/cap_rows"],
)
def clickhouse_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    # Return-None contract: write_out is NOT invoked.
    return None


# --- schema evolution (both write cap_evolve; run v1 then v2) ----------------
@subscriber(
    destination=ClickHouseDest(tables=["cap_evolve"], if_table_exists="replace"),
    input_tables=["caps_input/cap_evo_v1"],
)
def clickhouse_evolve_v1(v1: TableFrameSpec) -> TableFrameSpec:
    # Narrow schema (code, name) -> (re)creates cap_evolve.
    return v1


@subscriber(
    destination=ClickHouseDest(
        tables=["cap_evolve"],
        if_table_exists="append",
        # update -> add the new `population` column instead of refusing the batch
        # (which "strict", the default, would do).
        schema_evolution="update",
    ),
    input_tables=["caps_input/cap_evo_v2"],
)
def clickhouse_evolve_v2(v2: TableFrameSpec) -> TableFrameSpec:
    # Wide schema (code, name, population) appended -> evolves cap_evolve's schema.
    return v2
