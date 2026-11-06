#
# Copyright 2026 Tabsdata Inc.
#

"""medallion · extra · silver — identity pass-through transformers producing UNUSED silver tables.

Nothing to do with the medallion logic: 5 identity transformers, each tapping an existing
silver table (`<sys>_in_silver/append_silver`) via `@NEW` — cycling across the 6 source systems — and
re-emitting it VERBATIM as `extra_silver_NN` in the `extra_silver` collection. Nothing downstream
reads these tables; they exist only to add 5 extra, unused leaf tables that are generated
whenever the medallion append chain runs (the same `pub_append_events` triggers that feed the real
silver tables). See ../../extra.json / ../../xsuite.json."""

from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer
from tabsdatak.tableframe.functions import concat


@transformer(
    input_tables=["mysql_in_silver/append_silver@NEW"],
    output_tables=["extra_silver_01"],
)
def tfr_extra_silver_01(t_versions: TableFramesSpec) -> TableFrameSpec:
    # Identity: re-emit mysql_in_silver/append_silver unchanged as an unused leaf copy.
    t = concat(t_versions or [])
    return t

@transformer(
    input_tables=["postgres_in_silver/append_silver@NEW"],
    output_tables=["extra_silver_02"],
)
def tfr_extra_silver_02(t_versions: TableFramesSpec) -> TableFrameSpec:
    # Identity: re-emit postgres_in_silver/append_silver unchanged as an unused leaf copy.
    t = concat(t_versions or [])
    return t

@transformer(
    input_tables=["oracle_in_silver/append_silver@NEW"],
    output_tables=["extra_silver_03"],
)
def tfr_extra_silver_03(t_versions: TableFramesSpec) -> TableFrameSpec:
    # Identity: re-emit oracle_in_silver/append_silver unchanged as an unused leaf copy.
    t = concat(t_versions or [])
    return t

@transformer(
    input_tables=["db2_in_silver/append_silver@NEW"],
    output_tables=["extra_silver_04"],
)
def tfr_extra_silver_04(t_versions: TableFramesSpec) -> TableFrameSpec:
    # Identity: re-emit db2_in_silver/append_silver unchanged as an unused leaf copy.
    t = concat(t_versions or [])
    return t

@transformer(
    input_tables=["mssqlserver_in_silver/append_silver@NEW"],
    output_tables=["extra_silver_05"],
)
def tfr_extra_silver_05(t_versions: TableFramesSpec) -> TableFrameSpec:
    # Identity: re-emit mssqlserver_in_silver/append_silver unchanged as an unused leaf copy.
    t = concat(t_versions or [])
    return t
