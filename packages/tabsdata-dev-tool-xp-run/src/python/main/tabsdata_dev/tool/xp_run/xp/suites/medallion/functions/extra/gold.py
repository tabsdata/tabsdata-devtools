#
# Copyright 2026 Tabsdata Inc.
#

"""medallion · extra · gold — identity pass-through transformers producing UNUSED gold tables.

Nothing to do with the medallion logic: 20 identity transformers, each tapping an existing
gold table (`<sys>_in_gold/fct_append`) via `@NEW` — cycling across the 6 source systems — and
re-emitting it VERBATIM as `extra_gold_NN` in the `extra_gold` collection. Nothing downstream
reads these tables; they exist only to add 20 extra, unused leaf tables that are generated
whenever the medallion append chain runs (the same `pub_append_events` triggers that feed the real
gold tables). See ../../extra.json / ../../xsuite.json."""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["mysql_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_01"],
)
def tfr_extra_gold_01(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_02"],
)
def tfr_extra_gold_02(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_03"],
)
def tfr_extra_gold_03(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_04"],
)
def tfr_extra_gold_04(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_05"],
)
def tfr_extra_gold_05(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_06"],
)
def tfr_extra_gold_06(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_07"],
)
def tfr_extra_gold_07(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_08"],
)
def tfr_extra_gold_08(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_09"],
)
def tfr_extra_gold_09(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_10"],
)
def tfr_extra_gold_10(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_11"],
)
def tfr_extra_gold_11(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_12"],
)
def tfr_extra_gold_12(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_13"],
)
def tfr_extra_gold_13(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_14"],
)
def tfr_extra_gold_14(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_15"],
)
def tfr_extra_gold_15(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_16"],
)
def tfr_extra_gold_16(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_17"],
)
def tfr_extra_gold_17(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_18"],
)
def tfr_extra_gold_18(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_19"],
)
def tfr_extra_gold_19(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_gold/fct_append unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_gold/fct_append@NEW"],
    output_tables=["extra_gold_20"],
)
def tfr_extra_gold_20(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_gold/fct_append unchanged as an unused leaf copy.
    return t
