#
# Copyright 2026 Tabsdata Inc.
#

"""caps_localfile — exercise the local-file connector's full config surface: every
DATA FORMAT (write + read) plus the source selection modes (wildcard, last-modified,
multi, none).

Layout (all in localfile.json):
- WRITERS (`@subscriber`, collection ``localfile_out``, domain ``fs``): take the
  datagen ``caps_input/cap_rows`` frame and write it to the ``fs`` domain root in each
  ``DestFileFormat`` — CSV, JSON, AVRO, PARQUET — plus a CSV variant with custom
  ``format_cfg`` (``;`` separator, header). These fire off the ``caps_rows`` publish.
- ROUND-TRIP READERS (`@publisher`, collection ``localfile_rt``, domain ``fs``): read
  each written file back with the matching ``SrcFileFormat``. Because a file must exist
  before it can be read, these are registered but NOT auto-triggered — run them in a
  SECOND phase, after the writers have committed (e.g. `tdk fn trigger` each, or add
  them to the trigger list for a re-run).
- SEED READERS (`@publisher`, collection ``localfile_in``, domain ``fs_world_xs``):
  the wildcard / last-modified / multi / none selection modes, reading the seeded
  world parquet — using existing domain data (no round-trip needed).

File sources are ARRAY mode (a path may glob), so their params are lists indexed
``[0]``; DataGenSrc-fed subscribers get a single frame per input slot.

SRC METADATA — the ``tabsdata.src_metadata.drop`` contract: ``localfile_meta_keep`` and
``localfile_meta_drop`` (collection ``localfile_in``) read the same staged ``country``
parquet with and without that ``src_cfg`` key, and one ``@transformer`` each in
collection ``localfile_meta`` asserts that side: ``localfile_meta_keep_check`` that
``@td.file.path`` is there (none null, and the data columns are exactly the ones asked
for), ``localfile_meta_drop_check`` that no ``@td.`` column is left and the data columns
are unchanged. See functions/_srcmeta.py, which also explains why one transformer over
both tables cannot work.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import (
    TableFrameSpec, TableFramesSpec, publisher, subscriber, transformer,
)
from tabsdatak.conn.common.file.typing_ import DestFileFormat, SrcFileFormat
from tabsdatak.conn.localfile import LocalFileDest, LocalFileSrc
from tabsdatak.tableframe.functions import concat

try:
    from ._srcmeta import (
        COUNTRY_COLUMNS, DROP_METADATA, FILE_META, check_drop, check_keep,
    )
except ImportError:
    from _srcmeta import (
        COUNTRY_COLUMNS, DROP_METADATA, FILE_META, check_drop, check_keep,
    )

_IN = ["caps_input/cap_rows"]  # datagen-generated input for every writer


# --- WRITERS: one DestFileFormat each (fs domain root) -----------------------
@subscriber(destination=LocalFileDest(paths=["caps_out.csv"], format=DestFileFormat.CSV),
            input_tables=_IN)
def localfile_out_csv(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=LocalFileDest(paths=["caps_out.json"], format=DestFileFormat.JSON),
            input_tables=_IN)
def localfile_out_json(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=LocalFileDest(paths=["caps_out.avro"], format=DestFileFormat.AVRO),
            input_tables=_IN)
def localfile_out_avro(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=LocalFileDest(paths=["caps_out.parquet"], format=DestFileFormat.PARQUET),
            input_tables=_IN)
def localfile_out_parquet(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(
    destination=LocalFileDest(
        paths=["caps_out_opts.csv"],
        format=DestFileFormat.CSV,
        # CSV is the only format that takes format_cfg (keyed by the format enum).
        format_cfg={DestFileFormat.CSV: {"separator": ";", "include_header": True}},
    ),
    input_tables=_IN,
)
def localfile_out_csvopts(rows: TableFrameSpec) -> TableFrameSpec:
    return rows


@subscriber(destination=LocalFileDest(paths=["caps_out_none.parquet"], format=DestFileFormat.PARQUET),
            input_tables=_IN)
def localfile_out_none(rows: TableFrameSpec) -> TableFrameSpec:
    # Return-None contract: write_out is NOT invoked.
    return None


# --- ROUND-TRIP READERS: read each written file back (fs domain root) ---------
# Phase 2 — run after the writers have committed (the files must exist first).
@publisher(source=LocalFileSrc(paths=["caps_out.csv"], format=SrcFileFormat.CSV),
           output_tables=["cap_rt_csv"])
def localfile_rt_csv(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=LocalFileSrc(paths=["caps_out.json"], format=SrcFileFormat.JSON),
           output_tables=["cap_rt_json"])
def localfile_rt_json(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=LocalFileSrc(paths=["caps_out.avro"], format=SrcFileFormat.AVRO),
           output_tables=["cap_rt_avro"])
def localfile_rt_avro(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


@publisher(source=LocalFileSrc(paths=["caps_out.parquet"], format=SrcFileFormat.PARQUET),
           output_tables=["cap_rt_parquet"])
def localfile_rt_parquet(rows: TableFramesSpec) -> TableFrameSpec:
    return rows[0] if rows else None


# --- SEED READERS: selection modes over the seeded world parquet (fs_world_xs) -
@publisher(source=LocalFileSrc(paths=["parquet/city*.parquet"]),
           output_tables=["cap_glob"])
def localfile_in_glob(matches: TableFramesSpec) -> TableFrameSpec:
    # Wildcard -> one array slot with every match.
    return matches[0] if matches else None


@publisher(
    source=LocalFileSrc(
        paths=["parquet/country_2*.parquet"],
        initial_last_modified=datetime(2000, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["cap_since"],
)
def localfile_in_since(country: TableFramesSpec) -> TableFrameSpec:
    # mtime cutoff (auto-advances across runs).
    return country[0] if country else None


@publisher(source=LocalFileSrc(paths=["parquet/*.parquet"]),
           output_tables=["cap_multi"])
def localfile_in_multi(matches: TableFramesSpec) -> TableFrameSpec:
    # One wildcard slot -> union all matched frames.
    return concat(matches, how="diagonal")


@publisher(
    source=LocalFileSrc(
        paths=["parquet/country_2*.parquet"],
        initial_last_modified=datetime(2999, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["cap_none"],
)
def localfile_in_none(country: TableFramesSpec) -> TableFrameSpec:
    # Far-future cutoff -> empty slot -> publish None.
    frame = country[0] if country else None
    return None if frame is None else frame


# --- src metadata: the `tabsdata.src_metadata.drop` contract ------------------
# TWO READS OF THE SAME FILE differing only in that src_cfg key, each with its OWN
# assertion transformer — functions/_srcmeta.py holds the assertions and the reasoning,
# including why one transformer reading both tables cannot work. A file source reports
# `@td.file.path` — the path each row was read from — unless the key drops it.
_META_PATHS = ["parquet/country_2*.parquet"]


@publisher(source=LocalFileSrc(paths=_META_PATHS), output_tables=["meta_keep"])
def localfile_meta_keep(country: TableFramesSpec) -> TableFrameSpec:
    # Array slot (the path globs the staged file's timestamp away): one match.
    return country[0] if country else None


@publisher(
    source=LocalFileSrc(paths=_META_PATHS, src_cfg=DROP_METADATA),
    output_tables=["meta_drop"],
)
def localfile_meta_drop(country: TableFramesSpec) -> TableFrameSpec:
    return country[0] if country else None


@transformer(input_tables=["localfile_in/meta_keep@NEW"], output_tables=["meta_keep_ok"])
def localfile_meta_keep_check(keep: TableFrameSpec) -> TableFrameSpec:
    return check_keep(keep, FILE_META, COUNTRY_COLUMNS)


@transformer(input_tables=["localfile_in/meta_drop@NEW"], output_tables=["meta_drop_ok"])
def localfile_meta_drop_check(drop: TableFrameSpec) -> TableFrameSpec:
    return check_drop(drop, COUNTRY_COLUMNS)
