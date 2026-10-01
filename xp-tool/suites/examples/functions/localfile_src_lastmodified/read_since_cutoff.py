#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — local-file source: INCREMENTAL, `initial_last_modified` as a
moving cutoff.

HOW THE CUTOFF WORKS
    `initial_last_modified` is compared against each candidate file's
    modification time:

      * FIRST run  — import every matched file modified at or after the cutoff.
      * LATER runs — the cutoff has ADVANCED to the newest file the previous run
        imported, so only strictly newer files come through.

    The framework persists the advanced cutoff on the function's transaction
    state, so the value in the decorator is only ever the SEED: editing it does
    NOT rewind a function that has already run.

    Pass a TIMEZONE-AWARE datetime. A naive one is ambiguous against file mtimes.

    This is the file-source analogue of the SQL `initial_values` watermark —
    same idea, except a file source advances the cutoff for you, where a SQL
    source hands you `ctx` to advance it yourself.

The cutoff below is safely before anything this domain stages, so the first run
takes every matched file and each later run takes only what is newer.

DRIVING IT — run the project more than once
    1. `tdd xp one-shot --suite examples/localfile_src_lastmodified --keep`
    2. Stage a NEW file into the domain (the data plane is insert-only: every
       `modify-data` writes a new, freshly stamped file next to the seed):
           tdd domain modify-data --domain <XP_ID>_fs_world_xs \\
               --entity city --ops Insert --sets 5
    3. `tdd xp run-triggers --project <project> --monitor --time-out 30m`
    This reader imports only the new file on the second run.
"""
from __future__ import annotations

from datetime import datetime, timezone

from tabsdatak.api import TableFrameSpec, TableFramesSpec, publisher
from tabsdatak.conn.localfile import LocalFileSrc
from tabsdatak.tableframe.functions import concat


@publisher(
    source=LocalFileSrc(
        paths=["parquet/city_*.parquet"],
        initial_last_modified=datetime(2000, 1, 1, tzinfo=timezone.utc),
    ),
    output_tables=["city_new"],
)
def read_since_cutoff(city: TableFramesSpec) -> TableFrameSpec:
    # `concat` returns None for an empty list, so "no new files" publishes NO
    # version of the table at all — see read_future_cutoff.py.
    return concat(city)
