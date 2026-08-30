#
# Copyright 2026 Tabsdata Inc.
#
"""EXAMPLE · the ``examples`` suite with the storage swapped to S3.

The point this file makes: between local files and an object store, ONLY the
publisher's ``source=`` and the subscriber's ``destination=`` change. The grok
parsing and the marts are untouched -- the transformers below are IMPORTED from
the local-file twins (``gk_ex_cities`` / ``gk_ex_langs`` / ``gk_ex_join``), not
copied; a transform collection has no connection, so nothing in them knows (or
could know) where the lines came from or where the parquet goes.

The suite's collections do the switching: ``gk_logs`` is ``s3_file_in`` over an
S3 domain carrying the staged ``world`` model (the same ``csv/…`` tree an ``fs``
domain stages, just in a bucket prefix), ``gk_out`` is ``s3_file_out`` into a
plain S3 domain. The bucket, region, credentials and base path come from the
domains through the connection templates -- the code only names files.

Offline demos live in the twins (``python functions/gk_ex_<name>.py``); this
file adds no new parsing to demo.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher, subscriber
from tabsdatak.conn.common.file.typing_ import SrcFileFormat
from tabsdatak.conn.s3 import S3Dest, S3Src
from tabsdatak.tableframe.functions import concat

# Import order IS registration order (discovery walks the module namespace, and
# registration is serial): each parse_* must precede the mart_* that reads its table.
try:
    from .gk_ex_cities import parse_city_log, mart_big_cities  # noqa: F401
    from .gk_ex_langs import parse_lang_log, mart_official_languages  # noqa: F401
    from .gk_ex_join import jn_parse_cities, jn_parse_languages, mart_city_languages  # noqa: F401
except ImportError:
    from gk_ex_cities import parse_city_log, mart_big_cities  # noqa: F401
    from gk_ex_langs import parse_lang_log, mart_official_languages  # noqa: F401
    from gk_ex_join import jn_parse_cities, jn_parse_languages, mart_city_languages  # noqa: F401


# --- ingest: the same staged CSVs, now globbed out of the bucket (gk_logs) ----
@publisher(
    source=S3Src(paths=["csv/city_2*.csv"], format=SrcFileFormat.LOG),
    output_tables=["city_lines"],
)
def city_log_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(
    source=S3Src(paths=["csv/country_language_2*.csv"], format=SrcFileFormat.LOG),
    output_tables=["lang_lines"],
)
def lang_log_pub(lines: TableFramesSpec) -> TableFrameSpec:
    return concat(lines)


@publisher(
    source=S3Src(
        paths=["csv/city_2*.csv", "csv/country_language_2*.csv"],
        format=SrcFileFormat.LOG,
    ),
    output_tables=["jn_city_lines", "jn_lang_lines"],
)
def jn_log_pub(
    cities: TableFramesSpec, languages: TableFramesSpec
) -> tuple[TableFrameSpec, TableFrameSpec]:
    return concat(cities), concat(languages)


# --- serve: the same parquet names, landed in the S3 out domain (gk_out) ------
@subscriber(destination=S3Dest(paths=["cities.parquet"]), input_tables=["gk_marts/cities"])
def cities_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(destination=S3Dest(paths=["big_cities.parquet"]), input_tables=["gk_marts/big_cities"])
def big_cities_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(destination=S3Dest(paths=["languages.parquet"]), input_tables=["gk_marts/languages"])
def languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["official_languages.parquet"]),
    input_tables=["gk_marts/official_languages"],
)
def official_languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t


@subscriber(
    destination=S3Dest(paths=["city_languages.parquet"]),
    input_tables=["gk_marts/city_languages"],
)
def city_languages_out(t: TableFrameSpec) -> TableFrameSpec:
    return t
