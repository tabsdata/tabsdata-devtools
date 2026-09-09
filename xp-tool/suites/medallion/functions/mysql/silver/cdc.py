#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · silver · cdc — CDC SCD2 + SCD1 silver.

Part of the mysql medallion pipeline (source MySQL, domain mysql_bronze_xs). Collection mysql_in_silver; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

from tabsdatak._medallion.silver.scd import (
    build_scd1_silver,
    build_scd1_silver_cleanse,
    build_scd2_silver,
    build_scd2_silver_cleanse,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=[
        "mysql_in_bronze/cdc_bronze@NEW",
        "cdc_scd2_valid_raw@HEAD",
        "cdc_scd2_expired_raw@HEAD",
    ],
    output_tables=["cdc_scd2_valid_raw", "cdc_scd2_expired_raw"],
)
def tfr_cdc_scd2_change_detect(
    bronze: TableFramesSpec,
    valid_head: TableFrameSpec,
    expired_head: TableFrameSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return build_scd2_silver(
        bronze=bronze, valid_head=valid_head, expired_head=expired_head
    )


@transformer(
    input_tables=["cdc_scd2_valid_raw@NEW", "cdc_scd2_expired_raw@NEW"],
    output_tables=["cdc_valid_silver", "cdc_expired_silver"],
)
def tfr_cdc_scd2_cleanse(
    valid_raw: TableFramesSpec,
    expired_raw: TableFramesSpec,
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return build_scd2_silver_cleanse(valid_raw=valid_raw, expired_raw=expired_raw)


@transformer(
    input_tables=["mysql_in_bronze/cdc_bronze@NEW", "cdc_scd1_raw@HEAD"],
    output_tables=["cdc_scd1_raw"],
)
def tfr_cdc_scd1_change_detect(
    bronze: TableFramesSpec,
    scd1_head: TableFrameSpec,
) -> TableFrameSpec:
    return build_scd1_silver(bronze=bronze, scd1_head=scd1_head)


@transformer(
    input_tables=["cdc_scd1_raw@NEW"],
    output_tables=["cdc_current_silver"],
)
def tfr_cdc_scd1_cleanse(scd1_raw: TableFramesSpec) -> TableFrameSpec:
    return build_scd1_silver_cleanse(scd1_raw=scd1_raw)
