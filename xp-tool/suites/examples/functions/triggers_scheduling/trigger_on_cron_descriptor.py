#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — a cron mask written as a DESCRIPTOR rather than five fields.

`@hourly` is the same as `0 * * * *`, and the family is `@yearly` / `@annually`
/ `@monthly` / `@weekly` / `@daily` / `@midnight` / `@hourly`. Prefer the
descriptor when it says what you mean: `@daily` survives review better than
`0 0 * * *`, which one reader in three will parse as "every hour".

A FIXED frame here, not a chunked one — so every tick republishes the SAME three
rows. That is the other shape a schedule takes: the VERSION COUNT grows while the
row count stays at three, which is what a periodic full-snapshot of a small
reference table looks like.

This one will not fire inside a short test window, which is the point of
including it: the schedule is the subject, not the output. The suite fires it by
hand so a plain run still produces a batch — `trigger_by` and a manual
`tdk fn trigger` coexist happily.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import CronTrigger, TableFrameSpec, publisher
from tabsdatak.conn.dev import Data, DataGenSrc


@publisher(
    source=DataGenSrc(
        data=[
            Data(pl.DataFrame({
                "code": ["USA", "ESP", "JPN"],
                "name": ["United States", "Spain", "Japan"],
            }))
        ]
    ),
    output_tables=["hourly_snapshot"],
    trigger_by=CronTrigger(mask="@hourly"),
)
def trigger_on_cron_descriptor(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
