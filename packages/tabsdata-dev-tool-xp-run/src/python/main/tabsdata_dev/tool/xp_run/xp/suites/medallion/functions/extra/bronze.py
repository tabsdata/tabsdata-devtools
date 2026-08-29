#
# Copyright 2026 Tabsdata Inc.
#

"""medallion · extra · bronze — identity pass-through transformers producing UNUSED bronze tables.

Nothing to do with the medallion logic: 30 identity transformers, each tapping an existing
bronze table (`<sys>_in_bronze/append_bronze`) via `@NEW` — cycling across the 6 source systems — and
re-emitting it VERBATIM as `extra_bronze_NN` in the `extra_bronze` collection. Nothing downstream
reads these tables; they exist only to add 30 extra, unused leaf tables that are generated
whenever the medallion append chain runs (the same `pub_append_events` triggers that feed the real
bronze tables). See ../../extra.json / ../../xsuite.json."""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, transformer


@transformer(
    input_tables=["mysql_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_01"],
)
def tfr_extra_bronze_01(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_02"],
)
def tfr_extra_bronze_02(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_03"],
)
def tfr_extra_bronze_03(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_04"],
)
def tfr_extra_bronze_04(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_05"],
)
def tfr_extra_bronze_05(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_06"],
)
def tfr_extra_bronze_06(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_07"],
)
def tfr_extra_bronze_07(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_08"],
)
def tfr_extra_bronze_08(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_09"],
)
def tfr_extra_bronze_09(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_10"],
)
def tfr_extra_bronze_10(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_11"],
)
def tfr_extra_bronze_11(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_12"],
)
def tfr_extra_bronze_12(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_13"],
)
def tfr_extra_bronze_13(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_14"],
)
def tfr_extra_bronze_14(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_15"],
)
def tfr_extra_bronze_15(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_16"],
)
def tfr_extra_bronze_16(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_17"],
)
def tfr_extra_bronze_17(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_18"],
)
def tfr_extra_bronze_18(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_19"],
)
def tfr_extra_bronze_19(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_20"],
)
def tfr_extra_bronze_20(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_21"],
)
def tfr_extra_bronze_21(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_22"],
)
def tfr_extra_bronze_22(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_23"],
)
def tfr_extra_bronze_23(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_24"],
)
def tfr_extra_bronze_24(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mysql_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_25"],
)
def tfr_extra_bronze_25(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["postgres_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_26"],
)
def tfr_extra_bronze_26(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["oracle_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_27"],
)
def tfr_extra_bronze_27(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["db2_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_28"],
)
def tfr_extra_bronze_28(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["mssqlserver_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_29"],
)
def tfr_extra_bronze_29(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t

@transformer(
    input_tables=["databricks_in_bronze/append_bronze@NEW"],
    output_tables=["extra_bronze_30"],
)
def tfr_extra_bronze_30(t: TableFrameSpec) -> TableFrameSpec:
    # Identity: re-emit databricks_in_bronze/append_bronze unchanged as an unused leaf copy.
    return t
