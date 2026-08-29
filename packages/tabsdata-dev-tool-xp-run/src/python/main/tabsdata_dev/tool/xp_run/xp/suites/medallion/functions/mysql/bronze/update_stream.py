#
# Copyright 2026 Tabsdata Inc.
#

"""mysql · bronze · update_stream — update-stream bronze (build_upd_cdc_bronze).

Part of the mysql medallion pipeline (source MySQL, domain mysql_bronze_xs). Collection mysql_in_bronze; tables are referenced cross-collection between layers and bare within a layer."""


from __future__ import annotations

import tabsdatak.tableframe.datatypes as td_types
from tabsdatak._medallion.bronze.upd_cdc import build_upd_cdc_bronze
from tabsdatak.api import TableFrameSpec, TableFramesSpec, transformer


@transformer(
    input_tables=[
        "mysql_in_src/update_full_raw@NEW",
        "mysql_in_src/update_raw@NEW",
        "update_bronze@HEAD",
    ],
    output_tables=["update_bronze"],
)
def tfr_upd_bronze(
    full_commits: TableFramesSpec,
    upd_commits: TableFramesSpec,
    prior_bronze: TableFrameSpec,
) -> TableFrameSpec:
    return build_upd_cdc_bronze(
        full_commits=full_commits,
        upd_commits=upd_commits,
        prior_bronze=prior_bronze,
        pk=[{"tenant_id": td_types.String}, {"entity_id": td_types.Int64}],
        updated_ts_col="data_ts",
        is_delete_col="deleted",
    )
