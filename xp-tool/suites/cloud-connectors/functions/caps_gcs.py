#
# Copyright 2026 Tabsdata Inc.
#

"""caps_gcs — GCS file connector: all DATA FORMATS (write + read round-trip) plus source
selection modes (glob/since/multi/none). Mirrors caps_localfile with the GCS classes.

WRITERS (`@subscriber`, collection ``gcs_out``, domain ``gcs``): datagen ``caps_input/cap_rows``
-> bucket root in each format. ROUND-TRIP READERS (``gcs_rt``, same ``s3`` domain): read each
back (phase 2 — after writers commit). SEED READERS (``gcs_in``, ``gcs_world_xs``): glob/since/
multi/none over the seeded world parquet.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``gcs_meta_keep`` and
``gcs_meta_drop`` (collection ``gcs_in``) read the same staged ``country`` parquet with
and without that ``src_cfg`` key, and one ``@transformer`` each in collection
``gcs_meta`` asserts that side: ``gcs_meta_keep_check`` that ``@td.file.path`` is there
(none null, and the data columns are exactly the ones asked for),
``gcs_meta_drop_check`` that no ``@td.`` column is left and the data columns are
unchanged. See functions/_srcmeta.py, which also explains why one transformer over both
tables cannot work.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import (
    TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer,
)
from tabsdatak.conn.common.file.typing_ import DestFileFormat, SrcFileFormat
from tabsdatak.conn.gcs import GCSDest, GCSSrc
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


@subscriber(destination=GCSDest(paths=["caps_out.csv"], format=DestFileFormat.CSV), input_tables=_IN)
def gcs_out_csv(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=GCSDest(paths=["caps_out.json"], format=DestFileFormat.JSON), input_tables=_IN)
def gcs_out_json(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=GCSDest(paths=["caps_out.avro"], format=DestFileFormat.AVRO), input_tables=_IN)
def gcs_out_avro(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=GCSDest(paths=["caps_out.parquet"], format=DestFileFormat.PARQUET), input_tables=_IN)
def gcs_out_parquet(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=GCSDest(
        paths=["caps_out_opts.csv"], format=DestFileFormat.CSV,
        format_cfg={DestFileFormat.CSV: {"separator": ";", "include_header": True}},
    ),
    input_tables=_IN,
)
def gcs_out_csvopts(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=GCSDest(paths=["caps_out_none.parquet"], format=DestFileFormat.PARQUET), input_tables=_IN)
def gcs_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    return None


# round-trip readers (phase 2)
@publisher(source=GCSSrc(paths=["caps_out.csv"], format=SrcFileFormat.CSV), output_tables=["cap_rt_csv"])
def gcs_rt_csv(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=GCSSrc(paths=["caps_out.json"], format=SrcFileFormat.JSON), output_tables=["cap_rt_json"])
def gcs_rt_json(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=GCSSrc(paths=["caps_out.avro"], format=SrcFileFormat.AVRO), output_tables=["cap_rt_avro"])
def gcs_rt_avro(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=GCSSrc(paths=["caps_out.parquet"], format=SrcFileFormat.PARQUET), output_tables=["cap_rt_parquet"])
def gcs_rt_parquet(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


# seed readers: selection modes over seeded world parquet
@publisher(source=GCSSrc(paths=["parquet/city*.parquet"]), output_tables=["cap_glob"])
def gcs_in_glob(matches: TableFramesSpec) -> TableFrameSpec:
    return matches[0] if matches else None


@publisher(
    source=GCSSrc(paths=["parquet/country_2*.parquet"],
                 initial_last_modified=datetime(2000, 1, 1, tzinfo=timezone.utc)),
    output_tables=["cap_since"],
)
def gcs_in_since(country: TableFramesSpec) -> TableFrameSpec:
    return country[0] if country else None


@publisher(source=GCSSrc(paths=["parquet/*.parquet"]), output_tables=["cap_multi"])
def gcs_in_multi(matches: TableFramesSpec) -> TableFrameSpec:
    return concat(matches, how="diagonal")


@publisher(
    source=GCSSrc(paths=["parquet/country_2*.parquet"],
                 initial_last_modified=datetime(2999, 1, 1, tzinfo=timezone.utc)),
    output_tables=["cap_none"],
)
def gcs_in_none(country: TableFramesSpec) -> TableFrameSpec:
    frame = country[0] if country else None
    return None if frame is None else frame


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME FILE differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A file source reports
# `@td.file.path` — the path each row was read from — unless the key drops it.
_META_PATHS = ["parquet/country_2*.parquet"]


@publisher(source=GCSSrc(paths=_META_PATHS), output_tables=["meta_keep"])
def gcs_meta_keep(country: TableFramesSpec) -> TableFrameSpec:
    # Array slot (the path globs the staged file's timestamp away): one match.
    return country[0] if country else None


@publisher(
    source=GCSSrc(paths=_META_PATHS, src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def gcs_meta_drop(country: TableFramesSpec) -> TableFrameSpec:
    return country[0] if country else None


@transformer(input_tables=["gcs_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def gcs_meta_keep_check(keep_versions: TableFramesSpec) -> TableFrameSpec:
    keep = concat(keep_versions or [])
    return check_keep(keep, FILE_META, COUNTRY_COLUMNS)


@transformer(input_tables=["gcs_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def gcs_meta_drop_check(drop_versions: TableFramesSpec) -> TableFrameSpec:
    drop = concat(drop_versions or [])
    return check_drop(drop, COUNTRY_COLUMNS)
