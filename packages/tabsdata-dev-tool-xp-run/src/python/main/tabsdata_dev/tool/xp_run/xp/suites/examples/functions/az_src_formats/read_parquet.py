#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Azure Blob source: reading PARQUET, with nothing to configure.

No `format` at all: `AUTO` infers PARQUET from the extension. Parquet carries
its own schema and its own types, so there is no dialect to agree on and no
`format_cfg` to get wrong — which is why it is the format to prefer for anything
one Tabsdata function writes and another reads back.

A `azureblob` domain seeded with the `world` model stages every entity in THREE
formats, one directory each — `csv/<entity>_<stamp>.csv`,
`ndjson/<entity>_<stamp>.ndjson`, `parquet/<entity>_<stamp>.parquet` — so the
three readers in this suite read the SAME rows three ways and differ in exactly
one field. The `<stamp>` is the staging time, which is why each path is a
wildcard.

A WILDCARD IS A PREFIX MATCH, and this model is a good reminder of what that
costs: `country_*` also matches `country_language_*`, so a slot you expected to
hold one file holds two — of 23 and 12 columns — and `concat` fails on the shape
rather than telling you the pattern was too wide. These readers use `city_*`,
which no other entity extends.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.azureblob import AzureBlobSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=AzureBlobSrc(paths=["parquet/city_*.parquet"]),
    output_tables=["city_from_parquet"],
)
def read_parquet(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
