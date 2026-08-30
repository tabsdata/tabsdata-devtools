#
# Copyright 2026 Tabsdata Inc.
#
"""TESTS · the ``world_csv`` suite with the storage swapped to S3.

The grok calls under test and their assertions are IMPORTED from the local-file
test modules -- transformers and subscribers are connection-less (the sink is
TrashDest), so the only thing this file defines is one S3 publisher per case,
reading the same staged world CSVs out of the S3 domain's bucket prefix. Same
tables, same expectations; only the publisher's ``source=`` differs.

Offline: each case still self-checks through its own module
(``python functions/gk_<name>.py`` style; see _harness.py).
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.s3 import S3Src
from tabsdatak.tableframe.functions import concat

try:
    from .gk_split import CASE as SPLIT, split_tfr, split_sub  # noqa: F401
    from .gk_rename import CASE as RENAME, rename_tfr, rename_sub  # noqa: F401
    from .gk_types import CASE as TYPES, types_tfr, types_sub  # noqa: F401
    from .gk_nomatch import CASE as NOMATCH, nomatch_tfr, nomatch_sub  # noqa: F401
    from .gk_country import CASE as COUNTRY, country_tfr, country_sub  # noqa: F401
except ImportError:
    from gk_split import CASE as SPLIT, split_tfr, split_sub  # noqa: F401
    from gk_rename import CASE as RENAME, rename_tfr, rename_sub  # noqa: F401
    from gk_types import CASE as TYPES, types_tfr, types_sub  # noqa: F401
    from gk_nomatch import CASE as NOMATCH, nomatch_tfr, nomatch_sub  # noqa: F401
    from gk_country import CASE as COUNTRY, country_tfr, country_sub  # noqa: F401


@publisher(source=S3Src(paths=SPLIT.paths, format=SrcFileFormat.LOG), output_tables=[SPLIT.table])
def split_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(source=S3Src(paths=RENAME.paths, format=SrcFileFormat.LOG), output_tables=[RENAME.table])
def rename_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(source=S3Src(paths=TYPES.paths, format=SrcFileFormat.LOG), output_tables=[TYPES.table])
def types_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(source=S3Src(paths=NOMATCH.paths, format=SrcFileFormat.LOG), output_tables=[NOMATCH.table])
def nomatch_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(source=S3Src(paths=COUNTRY.paths, format=SrcFileFormat.LOG), output_tables=[COUNTRY.table])
def country_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)
