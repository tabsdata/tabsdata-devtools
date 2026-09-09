#
# Copyright 2026 Tabsdata Inc.
#

"""caps_cron — exercise the TRIGGER family (``trigger_by``) end to end, driven by the
dev DataGenSrc so no external system is involved.

Every other suite in this dir fires its functions manually (the suite's ``triggers``
list -> ``tdk fn trigger``). Here the functions carry their own ``trigger_by``, so the
runtime fires them: three cron publishers on a schedule, then a ``TablesTrigger``
transformer and an ``AllTablesTrigger`` subscriber that follow automatically. The whole
chain runs with nothing but the ``dev`` domain (DataGenSrc in, TrashDest out).

Cron masks are Kubernetes CronJob schedules — five UNIX fields (UTC, minute
granularity: there is no seconds field) or one of the descriptors ``@yearly``,
``@annually``, ``@monthly``, ``@weekly``, ``@daily``, ``@midnight``, ``@hourly``.

PUBLISHERS (`@publisher` + ``CronTrigger``, collection ``cron_src``):
- ``cron_pub_min``    : ``* * * * *`` (every minute) over ``Data(_CHUNK, chunk_size=5)``
                        — each tick emits the NEXT 5 rows, so the table grows by 5 a
                        minute and walks all 20 rows in four ticks. Once the frame is
                        exhausted the slot arrives as ``None`` and nothing is published
                        (the run still happens, it just emits no batch). The headline
                        case: visible progress with zero manual triggering.
- ``cron_pub_2min``   : ``*/2 * * * *`` over a FIXED 3-row frame — every other minute
                        republishes the same rows, so the version count grows while the
                        row count stays at 3.
- ``cron_pub_hourly`` : ``@hourly`` — covers the DESCRIPTOR form of the mask. It will
                        not fire inside a short test window; the suite triggers this one
                        manually so a plain `run-project` still produces a batch.

DOWNSTREAM (the other two trigger kinds, which publishers cannot use):
- ``cron_tfr_tables`` : `@transformer` with ``TablesTrigger(tables=["cron_src/cron_chunk"])``
                        — fires when the every-minute publisher lands a batch, proving
                        the cron -> dependent-trigger chain. Row-preserving ``select``
                        (a transformer's output must stay row-preserving).
- ``cron_sub_all``    : `@subscriber` with ``AllTablesTrigger()`` — fires when ANY table
                        it reads produces a batch, into ``TrashDest`` (a no-op sink, so
                        the suite needs no destination backend).

A ``trigger_by`` function can ALSO be run by hand; the chunk cursor advances per RUN
whoever fired it. ``oneshot`` without ``--keep`` tears the project down as soon as the
monitor returns, which can be before the first tick — use ``--keep`` (or
``create-project``) and leave it running to watch the schedule work.
"""
from __future__ import annotations

import polars as pl
from tabsdatak.api import (
    AllTablesTrigger,
    CronTrigger,
    TableFrameSpec,
    TablesTrigger,
    publisher,
    subscriber,
    transformer,
)
from tabsdatak.conn.dev import Data, DataGenSrc, TrashDest
from tabsdatak.tableframe import TableFrame
from tabsdatak.tableframe.functions import col

# 20 rows walked 5-at-a-time, so four cron ticks consume the frame and the fifth
# publishes nothing — the chunk cursor is per-run state, not per-schedule.
_CHUNK = pl.DataFrame(
    {
        "id": list(range(1, 21)),
        "name": [f"row-{i:02d}" for i in range(1, 21)],
    }
)
# Fixed frame: every tick republishes these 3 rows (new version, same row count).
_ROWS = pl.DataFrame(
    {
        "code": ["USA", "ESP", "JPN"],
        "name": ["United States", "Spain", "Japan"],
    }
)


# --- cron publishers (collection `cron_src`) ---------------------------------
@publisher(
    source=DataGenSrc(data=[Data(_CHUNK, chunk_size=5)]),
    output_tables=["cron_chunk"],
    trigger_by=CronTrigger(mask="* * * * *"),
)
def cron_pub_min(chunk: TableFrameSpec) -> TableFrameSpec:
    # Every minute: the next 5 rows, then None once the 20 are spent.
    return chunk


@publisher(
    source=DataGenSrc(data=[Data(_ROWS)]),
    output_tables=["cron_rows"],
    trigger_by=CronTrigger(mask="*/2 * * * *"),
)
def cron_pub_2min(rows: TableFrameSpec) -> TableFrameSpec:
    # Every other minute: the same 3 rows again -> versions grow, row count does not.
    return rows


@publisher(
    source=DataGenSrc(data=[Data(_ROWS)]),
    output_tables=["cron_hourly"],
    trigger_by=CronTrigger(mask="@hourly"),
)
def cron_pub_hourly(rows: TableFrameSpec) -> TableFrameSpec:
    # Descriptor form of the mask. Too slow for a test window, so the suite fires this
    # one manually — the schedule itself is what is being covered here.
    return rows


# --- downstream triggers -----------------------------------------------------
@transformer(
    input_tables=["cron_src/cron_chunk"],
    output_tables=["cron_checked"],
    trigger_by=TablesTrigger(tables=["cron_src/cron_chunk"]),
)
def cron_tfr_tables(chunk: TableFrameSpec) -> TableFrameSpec:
    # Fires off the every-minute publisher's batch. `select` is row-preserving, which a
    # transformer's output has to be (an aggregate would not sink downstream).
    if chunk is None:
        return None
    return chunk.select(col("id"), col("name"))


@subscriber(
    destination=TrashDest(),
    input_tables=["cron_ops/cron_checked"],
    trigger_by=AllTablesTrigger(),
)
def cron_sub_all(checked: TableFrameSpec) -> TableFrameSpec:
    # AllTablesTrigger: fires when any table this function reads produces a batch.
    # TrashDest discards the rows, so no destination backend is needed.
    return TableFrame.empty() if checked is None else checked
