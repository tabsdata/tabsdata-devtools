#
# Copyright 2026 Tabsdata Inc.
#
"""Check the datagen_scale_samples suite's 50 tables against its plan.

    verify_dq_scale_samples.py [--deep TABLE]... [--time-out D] [--profile NAME]

The plan is ``functions/scale_plan.py``: which tables, their columns, which carry
boolean classifiers and which scale categorizers, and -- the data being made, not
drawn -- exactly how many rows of every trigger each boolean classifier passes,
fails, and leaves null or nan. The collection is the plan's; the project is
``$XP_PROJECT``; the files this reads are left under
``$XP_WORK_DIR/dq-scales/``. Per table:

- one version that changed data per trigger;
- with data quality, a ``<table>_dq_summary`` version per trigger, the latest holding
  exactly the plan's classifiers, its boolean tallies the plan's for the last
  trigger, every categorizer's bins, under, over, nan and none adding up to
  ``dq.total`` with an under- and an overflow;
- with boolean classifiers, ``<table>_dq_summary_trends`` holding a run row per
  classifier and trigger, the n-th run's passed, failed, nulls and nans the plan's
  for trigger n (so the pass rate moves on every run), and its week, month and
  folded rows adding up as ``verify_dq_trends.check`` has them.

A ``--deep`` TABLE has every summary version read too: its categorizers' histograms
must move from every version to the next, and its trend's run rows sum to its
summaries'. The trend is polled until it has caught up, for ``--time-out``.

The step's note counts the tables by kind and the classifiers checked.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import verify_dq_trends as v  # beside this script, which python puts on the path
from tdd import TddError, note

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))
import scale_plan as plan  # noqa: E402 -- standard library only

TREND_OF = {"dq.true": "passed", "dq.false": "failed", "dq.none": "nulls", "dq.nan": "nans"}


def expected_summaries(table: plan.Table) -> v.Summaries:
    """The summaries the plan makes, as ``verify_dq_trends.check`` reads them."""
    s = v.Summaries()
    for t in range(plan.TRIGGERS):
        for c, counts in plan.expected_booleans(table, t).items():
            s.runs[c] += 1
            for src, dst in TREND_OF.items():
                s.sums[c][dst] += counts[src]
    return s


def check_latest_summary(table: plan.Table, got: list[dict]) -> list[str]:
    problems = []
    by = {r["dq.classifier"]: r for r in got}
    want = set(table.classifiers())
    if set(by) != want:
        problems.append(f"{table.name}: summary classifiers differ: {sorted(set(by) ^ want)}")
    for c, counts in plan.expected_booleans(table, plan.TRIGGERS - 1).items() if table.booleans else ():
        if c in by and {k: int(v.num(by[c][k])) for k in counts} != counts:
            problems.append(f"{table.name}: {c} last summary {[by[c][k] for k in counts]}, the plan's {list(counts.values())}")
    for c, r in by.items():
        if r.get("dq.type") != "categorical":
            continue
        counts, total = v.histogram(r)
        if sum(counts) != total:
            problems.append(f"{table.name}: {c} counts {sum(counts):g} rows of a dq.total of {total:g}")
        if v.num(r["dq.under"]) <= 0 or v.num(r["dq.over"]) <= 0:
            problems.append(f"{table.name}: {c} under {r['dq.under']} over {r['dq.over']}: an end not seen")
    return problems


def check_runs(table: plan.Table, trend: list[dict]) -> list[str]:
    """The n-th run row of each classifier, by bucket, holds trigger n's counts."""
    problems = []
    runs: dict[str, list[dict]] = defaultdict(list)
    for r in sorted((r for r in trend if r["grain"] == v.RUN), key=lambda r: r["bucket"]):
        runs[r["classifier"]].append(r)
    for t in range(plan.TRIGGERS):
        for c, counts in plan.expected_booleans(table, t).items():
            rows = runs.get(c, [])
            if t >= len(rows):
                continue  # the count is v.check's
            got = {src: int(v.num(rows[t][dst])) for src, dst in TREND_OF.items()}
            if got != counts:
                problems.append(f"{table.name}: {c} run {t} {got}, the plan's {counts}")
    return problems[:10]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--deep", action="append", default=[], metavar="TABLE",
                        help="also read every summary version of TABLE; repeatable")
    parser.add_argument("--time-out", type=v.seconds, default=v.seconds("10m"),
                        help="how long the trends may take to catch up (default 10m)")
    parser.add_argument("--profile", default=None, metavar="NAME",
                        help="the tdk connection to read on; empty or absent: tdk's default")
    args = parser.parse_args()
    if args.profile:
        v.PROFILE[:] = ["--profile", args.profile]
    proj, coll = os.environ["XP_PROJECT"], plan.COLLECTION
    work = Path(os.environ["XP_WORK_DIR"]) / "dq-scales"
    work.mkdir(parents=True, exist_ok=True)
    tables = {t.name: t for t in plan.TABLES}
    unknown = [d for d in args.deep if d not in tables]
    if unknown:
        parser.error(f"not a table of the plan: {', '.join(unknown)}")

    problems: list[str] = []
    kinds: dict[str, int] = defaultdict(int)
    booleans = categorizers = 0
    deadline = time.monotonic() + args.time_out
    for table in plan.TABLES:
        kinds[table.dq] += 1
        found = v.changed_versions(proj, coll, table.name)
        if len(found) != plan.TRIGGERS:
            problems.append(f"{table.name}: {len(found)} version(s) changed data, not {plan.TRIGGERS}")
        if table.dq == "plain":
            continue
        summary = f"{table.name}_dq_summary"
        versions = v.changed_versions(proj, coll, summary)
        if len(versions) != plan.TRIGGERS:
            problems.append(f"{summary}: {len(versions)} version(s), not {plan.TRIGGERS}")
        if versions:
            problems += check_latest_summary(table, v.rows(proj, coll, summary, versions[-1]["id"], work))
        categorizers += sum(c.endswith("_category") for c in table.classifiers())
        deep = table.name in args.deep
        actual = v.Summaries()
        if deep:
            actual.update(proj, coll, summary, work)
            found_problems, _ = v.check_categories(table.name, actual, plan.TRIGGERS, True, True)
            problems += found_problems
        if not table.booleans:
            continue
        booleans += len(plan.expected_booleans(table, 0))
        want = actual if deep else expected_summaries(table)
        while True:
            trend = v.latest_trend(proj, coll, f"{summary}_trends", work)
            if not v.behind(want, trend):
                break
            if time.monotonic() > deadline:
                problems.append(f"{table.name}: the trend did not catch up in {args.time_out:g}s")
                break
            time.sleep(v.POLL_SECS)
        problems += v.check(table.name, want, trend, plan.TRIGGERS, moving=True)
        problems += check_runs(table, trend)
        print(f"{table.name}: {len(versions)} summary version(s), {len(trend)} trend row(s)")

    note(
        f"{len(plan.TABLES)} tables ("
        + ", ".join(f"{n} {k}" for k, n in sorted(kinds.items()))
        + f"), {plan.TRIGGERS} triggers; {booleans} boolean classifiers, {categorizers} categorizers"
    )
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TddError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
