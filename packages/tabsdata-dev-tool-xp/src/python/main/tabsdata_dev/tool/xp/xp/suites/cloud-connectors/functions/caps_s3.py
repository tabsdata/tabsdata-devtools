#
# Copyright 2026 Tabsdata Inc.
#

"""caps_s3 — S3 file connector: all DATA FORMATS (write + read round-trip) plus source
selection modes (glob/since/multi/none). Mirrors caps_localfile with the S3 classes.

WRITERS (`@subscriber`, collection ``s3_out``, domain ``s3``): datagen ``caps_input/cap_rows``
-> bucket root in each format. ROUND-TRIP READERS (``s3_rt``, same ``s3`` domain): read each
back (phase 2 — after writers commit). SEED READERS (``s3_in``, ``s3_world_xs``): glob/since/
multi/none over the seeded world parquet.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``s3_meta_keep`` and
``s3_meta_drop`` (collection ``s3_in``) read the same staged ``country`` parquet with
and without that ``src_cfg`` key, and one ``@transformer`` each in collection
``s3_meta`` asserts that side: ``s3_meta_keep_check`` that ``@td.file.path`` is there
(none null, and the data columns are exactly the ones asked for), ``s3_meta_drop_check``
that no ``@td.`` column is left and the data columns are unchanged. See
functions/_srcmeta.py, which also explains why one transformer over both tables cannot
work.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import (
    TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer,
)
from tabsdatak.conn.common.file.typing_ import DestFileFormat, SrcFileFormat
from tabsdatak.conn.s3 import S3Dest, S3Src
from tabsdatak.tableframe.functions import concat

try:
    from ._srcmeta import (
        COUNTRY_COLUMNS, DROP_METADATA, FILE_META, check_drop, check_keep,
    )
except ImportError:
    from _srcmeta import (
        COUNTRY_COLUMNS, DROP_METADATA, FILE_META, check_drop, check_keep,
    )

_IN = ["caps_input/cap_rows"]


@subscriber(destination=S3Dest(paths=["caps_out.csv"], format=DestFileFormat.CSV), input_tables=_IN)
def s3_out_csv(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=S3Dest(paths=["caps_out.json"], format=DestFileFormat.JSON), input_tables=_IN)
def s3_out_json(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=S3Dest(paths=["caps_out.avro"], format=DestFileFormat.AVRO), input_tables=_IN)
def s3_out_avro(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=S3Dest(paths=["caps_out.parquet"], format=DestFileFormat.PARQUET), input_tables=_IN)
def s3_out_parquet(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=S3Dest(
        paths=["caps_out_opts.csv"], format=DestFileFormat.CSV,
        format_cfg={DestFileFormat.CSV: {"separator": ";", "include_header": True}},
    ),
    input_tables=_IN,
)
def s3_out_csvopts(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=S3Dest(paths=["caps_out_none.parquet"], format=DestFileFormat.PARQUET), input_tables=_IN)
def s3_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# round-trip readers (phase 2)
@publisher(source=S3Src(paths=["caps_out.csv"], format=SrcFileFormat.CSV), output_tables=["cap_rt_csv"])
def s3_rt_csv(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=S3Src(paths=["caps_out.json"], format=SrcFileFormat.JSON), output_tables=["cap_rt_json"])
def s3_rt_json(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=S3Src(paths=["caps_out.avro"], format=SrcFileFormat.AVRO), output_tables=["cap_rt_avro"])
def s3_rt_avro(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=S3Src(paths=["caps_out.parquet"], format=SrcFileFormat.PARQUET), output_tables=["cap_rt_parquet"])
def s3_rt_parquet(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


# seed readers: selection modes over seeded world parquet
@publisher(source=S3Src(paths=["parquet/city*.parquet"]), output_tables=["cap_glob"])
def s3_in_glob(matches: TableFramesSpec) -> TableFrameSpec:
    return matches[0] if matches else None


@publisher(
    source=S3Src(paths=["parquet/country_2*.parquet"],
                 initial_last_modified=datetime(2000, 1, 1, tzinfo=timezone.utc)),
    output_tables=["cap_since"],
)
def s3_in_since(country: TableFramesSpec) -> TableFrameSpec:
    return country[0] if country else None


@publisher(source=S3Src(paths=["parquet/*.parquet"]), output_tables=["cap_multi"])
def s3_in_multi(matches: TableFramesSpec) -> TableFrameSpec:
    return concat(matches, how="diagonal")


@publisher(
    source=S3Src(paths=["parquet/country_2*.parquet"],
                 initial_last_modified=datetime(2999, 1, 1, tzinfo=timezone.utc)),
    output_tables=["cap_none"],
)
def s3_in_none(country: TableFramesSpec) -> TableFrameSpec:
    frame = country[0] if country else None
    return None if frame is None else frame


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME FILE differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A file source reports
# `@td.file.path` — the path each row was read from — unless the key drops it.
_META_PATHS = ["parquet/country_2*.parquet"]


@publisher(source=S3Src(paths=_META_PATHS), output_tables=["meta_keep"])
def s3_meta_keep(country: TableFramesSpec) -> TableFrameSpec:
    # Array slot (the path globs the staged file's timestamp away): one match.
    return country[0] if country else None


@publisher(
    source=S3Src(paths=_META_PATHS, src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def s3_meta_drop(country: TableFramesSpec) -> TableFrameSpec:
    return country[0] if country else None


@transformer(input_tables=["s3_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def s3_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, FILE_META, COUNTRY_COLUMNS)


@transformer(input_tables=["s3_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def s3_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, COUNTRY_COLUMNS)
