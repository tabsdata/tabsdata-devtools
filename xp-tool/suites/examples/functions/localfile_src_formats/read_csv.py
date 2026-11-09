#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file source: reading CSV, with `format` named explicitly.

`format` chooses the reader: `AUTO` (the default) infers it from the file
extension, and `CSV` / `JSON` / `AVRO` / `PARQUET` / `LOG` name it outright. The
extension would have inferred CSV here too — it is spelled out so the three
readers in this suite differ in exactly one thing.

A `fs` domain seeded with the `world` model stages every entity in FIVE
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
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(paths=["csv/city_*.csv"], format=SrcFileFormat.CSV),
    output_tables=["city_from_csv"],
)
def read_csv(city: TableFramesSpec) -> TableFrameSpec:
    return concat(city)
