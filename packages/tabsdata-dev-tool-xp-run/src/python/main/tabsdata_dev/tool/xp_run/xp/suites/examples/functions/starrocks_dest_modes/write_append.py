#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — StarRocks destination: `if_table_exists="append"` into a table that
already exists.

The target is the `city` table the `world` model seeded, because StarRocks CANNOT
CREATE A TABLE ON WRITE (see supporting_generate_world_rows.py). That single fact
is what makes this connector's write modes worth their own example: `append` and
`replace` mean the same as everywhere else, but "the table does not exist yet" is
an error rather than a create.

`city.id` is AUTO_INCREMENT and the frame omits it, so each run inserts rows with
FRESH keys and the count GROWS — 100 seeded, +3 per run.

STAGING: StarRocks loads from an OBJECT STORE named on the connection. This suite
stages through S3; `starrocks_bulk_out_gcs.yaml` and `_az.yaml` are the same
connector with a different staging store.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.starrocks import StarRocksDest


@subscriber(
    destination=StarRocksDest(tables=["city"], if_table_exists="append"),
    input_tables=["gen/world_city"],
)
def write_append(city: TableFrameSpec) -> TableFrameSpec:
    return city
