#
# Copyright 2026 Tabsdata Inc.
#
"""Check the salesforce-dq-trends suite's leads and leads_pipeline against its plan.

    verify_dq_salesforce.py [--time-out D] [--profile NAME]

The plan is ``functions/sf_leads_plan.py``: ten runs of a Lead Lifetime report,
100 leads each, and -- the data being made, not drawn -- exactly how many rows of
every run each classifier passes, fails and leaves null, and how many land in
every bucket of the two categorizers. The collections and tables are the plan's;
the project is ``$XP_PROJECT``; the files this reads are left under
``$XP_WORK_DIR/sf-leads/``.

- ``leads`` and ``leads_pipeline``: a version per run that changed data, of 100
  rows where tdk says;
- ``leads_dq_summary``: a version per run, the n-th holding exactly the plan's
  boolean classifiers and its tallies for run n;
- ``leads_pipeline_dq_summary``: a version per run, the n-th holding exactly the
  two categorizers and run n's histograms bucket by bucket, adding up and moving
  from every run to the next;
- ``leads_dq_summary_trends``: polled until it has caught up, for ``--time-out``,
  then a run row per classifier and run, the n-th run's passed, failed and nulls
  run n's, and its week, month and folded rows adding up as
  ``verify_dq_trends.check`` has them.

The step's note says how each classifier's failures went from the first run to the
last.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

from tdd import TddError, note

# The plan beside the suite, and the trend checks the dataquality trends suites share.
_SUITES = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))
sys.path.insert(0, str(_SUITES / "dataquality" / "trends" / "scripts"))
import sf_leads_plan as plan  # noqa: E402 -- standard library only
import verify_dq_trends as v  # noqa: E402

TREND_OF = {"dq.true": "passed", "dq.false": "failed", "dq.none": "nulls", "dq.nan": "nans"}
OUT_OF_BINS = ("dq.under", "dq.over", "dq.none", "dq.nan")


def filled(r: dict) -> dict[str, int]:
    """A categorizer's summary row as the plan has it: every column holding rows."""
    return {
        k: int(v.num(x))
        for k, x in r.items()
        if (v.BIN.fullmatch(k) or k in OUT_OF_BINS) and v.num(x)
    }


def check_summary(t: int, got: list[dict], booleans: bool) -> list[str]:
    """Run `t`'s summary -- the leads' booleans or the pipeline's categorizers --
    its classifiers and their tallies or histograms the plan's."""
    problems = []
    by = {r["dq.classifier"]: r for r in got}
    want = plan.expected_booleans(t) if booleans else plan.expected_categories(t)
    if set(by) != set(want):
        problems.append(f"run {t}: summary classifiers differ: {sorted(set(by) ^ set(want))}")
    for c, counts in want.items():
        if c not in by:
            continue
        found = {k: int(v.num(by[c][k])) for k in counts} if booleans else filled(by[c])
        if found != counts:
            problems.append(f"run {t}: {c} {sorted(found.items())}, the plan's {sorted(counts.items())}")
    return problems


def check_runs(trend: list[dict]) -> list[str]:
    """The n-th run row of each classifier, by bucket, holds run n's counts."""
    problems = []
    runs: dict[str, list[dict]] = defaultdict(list)
    for r in sorted((r for r in trend if r["grain"] == v.RUN), key=lambda r: r["bucket"]):
        runs[r["classifier"]].append(r)
    for t in range(plan.TRIGGERS):
        for c, counts in plan.expected_booleans(t).items():
            rows = runs.get(c, [])
            if t >= len(rows):
                continue  # the count is v.check's
            got = {src: int(v.num(rows[t][dst])) for src, dst in TREND_OF.items()}
            if got != counts:
                problems.append(f"{c} run {t} {got}, the plan's {counts}")
    return problems[:10]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("--time-out", type=v.seconds, default=v.seconds("10m"),
                        help="how long the trend may take to catch up (default 10m)")
    parser.add_argument("--profile", default=None, metavar="NAME",
                        help="the tdk connection to read on; empty or absent: tdk's default")
    args = parser.parse_args()
    if args.profile:
        v.PROFILE[:] = ["--profile", args.profile]
    proj, coll, table = os.environ["XP_PROJECT"], plan.COLLECTION, plan.TABLE
    coll_of = {table: coll, plan.PIPELINE: plan.PIPELINE_COLLECTION}
    work = Path(os.environ["XP_WORK_DIR"]) / "sf-leads"
    work.mkdir(parents=True, exist_ok=True)

    problems: list[str] = []
    for name in (table, plan.PIPELINE):
        found = v.changed_versions(proj, coll_of[name], name)
        if len(found) != plan.TRIGGERS:
            problems.append(f"{name}: {len(found)} version(s) changed data, not {plan.TRIGGERS}")
        problems += [
            f"{name}: version {f['id']} holds {f['row_count']} row(s), not {plan.ROWS}"
            for f in found
            if f.get("row_count") not in (None, "") and int(f["row_count"]) != plan.ROWS
        ]

    for name, booleans in ((table, True), (plan.PIPELINE, False)):
        summary = f"{name}_dq_summary"
        versions = v.changed_versions(proj, coll_of[name], summary)
        if len(versions) != plan.TRIGGERS:
            problems.append(f"{summary}: {len(versions)} version(s), not {plan.TRIGGERS}")
        for t, found_version in enumerate(versions[: plan.TRIGGERS]):
            problems += check_summary(t, v.rows(proj, coll_of[name], summary, found_version["id"], work), booleans)
    pipeline = v.Summaries()
    pipeline.update(proj, plan.PIPELINE_COLLECTION, f"{plan.PIPELINE}_dq_summary", work)
    found_problems, _ = v.check_categories(plan.PIPELINE, pipeline, plan.TRIGGERS, moving=True, out_of_range=False)
    problems += found_problems

    summary = f"{table}_dq_summary"
    actual = v.Summaries()
    actual.update(proj, coll, summary, work)

    deadline = time.monotonic() + args.time_out
    while True:
        trend = v.latest_trend(proj, coll, f"{summary}_trends", work)
        if not v.behind(actual, trend):
            break
        if time.monotonic() > deadline:
            problems.append(f"{table}: the trend did not catch up in {args.time_out:g}s")
            break
        time.sleep(v.POLL_SECS)
    problems += v.check(table, actual, trend, plan.TRIGGERS)
    problems += check_runs(trend)
    print(f"{table}: {actual.runs and max(actual.runs.values())} summary version(s), {len(trend)} trend row(s)")

    first, last = plan.expected_booleans(0), plan.expected_booleans(plan.TRIGGERS - 1)
    note(
        f"{plan.TRIGGERS} runs of {plan.ROWS} leads; {len(plan.CHECKS)} boolean classifiers, "
        f"{len(plan.CATEGORIZERS)} categorizers; failures first->last run: "
        + ", ".join(
            f"{c.verdict} {first[c.name]['dq.false']}->{last[c.name]['dq.false']} ({plan.TRENDS[c.fails]})"
            for c in plan.CHECKS
        )
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
