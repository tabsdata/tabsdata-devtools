#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — NO `trigger_by`: the default, and the contrast the others need.

This publisher carries no trigger at all, so nothing starts it on its own. It
runs when something asks it to:

  * the suite descriptor's `triggers` list, which is what `tdx-xp run-project`
    fires (`tdk fn trigger --coll ... --name ...`), or
  * a hand-run `tdk fn trigger`, or
  * never, if nobody does either.

THAT IS THE RIGHT DEFAULT for a source you want to pull on demand — a backfill, a
migration, anything a human decides the timing of. Reach for `CronTrigger` when
the timing is a property of the DATA (it lands hourly, so read it hourly), not
when it is a property of your convenience.

The distinction matters more downstream: a `@transformer` or `@subscriber`
without `trigger_by` still fires REACTIVELY, when a table it reads with `@NEW`
gets a new version. Only a publisher is genuinely inert without help, because it
has no upstream table to react to.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "id": [1, 2, 3],
                "note": ["on demand", "not scheduled", "fired by hand"],
            }))
        ]
    ),
    output_tables=["on_demand"],
)
def trigger_manually(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
