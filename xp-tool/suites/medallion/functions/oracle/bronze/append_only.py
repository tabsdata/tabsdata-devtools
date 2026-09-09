#
# Copyright 2026 Tabsdata Inc.
#

"""oracle · bronze · append_only — append-only bronze (build_append_only_cdc_bronze).

Part of the oracle medallion pipeline (source Oracle, domain oracle_bronze_xs). Collection oracle_in_bronze; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

import tabsdatak.tableframe.datatypes as td_types
from tabsdatak._medallion.bronze.append_only_cdc import (
    build_append_only_cdc_bronze,
)
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=["oracle_in_src/append_raw@NEW"],
    output_tables=["append_bronze"],
)
def tfr_append_bronze(new: TableFramesSpec) -> TableFrameSpec:
    return build_append_only_cdc_bronze(
        new=new, pk=[{"sim_counter": td_types.Int64}], event_ts_col="data_ts"
    )
