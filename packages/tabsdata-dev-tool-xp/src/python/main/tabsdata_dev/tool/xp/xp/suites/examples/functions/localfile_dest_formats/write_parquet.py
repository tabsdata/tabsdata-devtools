#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file destination: PARQUET, with the format inferred.

No `format` at all: `AUTO` (the default) reads the `.parquet` extension. Parquet
carries its own schema and its own types, so the round trip is exact and there is
nothing to configure — the default choice for anything another Tabsdata function
will read back.

THE SHAPE OF A FILE DESTINATION
    `paths` declares one WRITE SLOT per entry, fed by `input_tables` in the SAME
    ORDER, and the function returns one frame per slot. A destination path names
    ONE file: no wildcards.

    Directories are real here, so a path with a `/` in it creates one.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from tabsdatak.conn.localfile import LocalFileDest


@subscriber(
    destination=LocalFileDest(paths=["customers.parquet"]),
    input_tables=["gen/customers"],
)
def write_parquet(customers: TableFrameSpec) -> TableFrameSpec:
    return customers
