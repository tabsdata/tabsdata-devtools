#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Azure Blob destination: PARQUET, with the format inferred.

No `format` at all: `AUTO` (the default) reads the `.parquet` extension. Parquet
carries its own schema and its own types, so the round trip is exact and there is
nothing to configure — the default choice for anything another Tabsdata function
will read back.

THE SHAPE OF A FILE DESTINATION
    `paths` declares one WRITE SLOT per entry, fed by `input_tables` in the SAME
    ORDER, and the function returns one frame per slot. A destination path names
    ONE file: no wildcards.

    There are no directories: a path with a `/` in it is one flat blob name.
    Paths are always relative to `base_path` — never an `az://` URI.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.azureblob import AzureBlobDest


@subscriber(
    destination=AzureBlobDest(paths=["customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_parquet(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
