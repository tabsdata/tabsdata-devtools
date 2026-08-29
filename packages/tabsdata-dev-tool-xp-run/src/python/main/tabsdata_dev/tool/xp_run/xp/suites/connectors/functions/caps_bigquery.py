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
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.bigquery import BigQueryDest


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
