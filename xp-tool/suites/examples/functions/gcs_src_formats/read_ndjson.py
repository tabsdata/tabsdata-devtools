#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — GCS source: reading NDJSON, the case `AUTO` cannot infer.

`.ndjson` is newline-delimited JSON, which is exactly what the JSON reader
wants — but `AUTO` does not recognise that extension, so the format has to be
NAMED. This is the single most common file-source surprise, and the rule that
follows from it is: name `format` whenever the extension does not say (`.ndjson`,
`.txt`, `.dat`, no extension at all).

A `gcs` domain seeded with the `world` model stages every entity in FIVE
formats, one directory each — `csv/<entity>_<stamp>.csv`,
`ndjson/<entity>_<stamp>.ndjson`, `parquet/<entity>_<stamp>.parquet`, and
`avro/` and `xlsx/`, which this suite does not read — so the three readers in
this suite read the SAME rows three ways and differ in exactly one field. The `<stamp>` is the staging time, which is why each path is a
wildcard.

A WILDCARD IS A PREFIX MATCH, and this model is a good reminder of what that
costs: `country_*` also matches `country_language_*`, so a slot you expected to
hold one file holds two — of 23 and 12 columns — and `concat` fails on the shape
rather than telling you the pattern was too wide. These readers use `city_*`,
which no other entity extends.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.gcs import GCSSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=GCSSrc(paths=["ndjson/city_*.ndjson"], format=SrcFileFormat.JSON),
    output_tables=["city_from_json"],
)
def read_ndjson(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
