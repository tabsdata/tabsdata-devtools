#
# Copyright 2026 Tabsdata Inc.
#

"""caps_snowflake — Snowflake bulk dest write modes (create/append/replace; no
schema_evolution). Input from the dev datagen ``caps_input/cap_rows`` frame.

- ``snowflake_out_append``  : ``if_table_exists="append"`` — create then accumulate.
- ``snowflake_out_replace`` : ``if_table_exists="replace"`` — create then TRUNCATE+reload.
- ``snowflake_out_none``    : return-None contract.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.snowflake import SnowflakeDest


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
