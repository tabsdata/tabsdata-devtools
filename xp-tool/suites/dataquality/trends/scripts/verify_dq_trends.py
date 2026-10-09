#
# Copyright 2026 Tabsdata Inc.
#
"""Check the DQ summary trend tables against the summaries they fold, and the
categorizers' summaries.

    verify_dq_trends.py COLLECTION TABLE... [--categorized TABLE]... [--cdc COLLECTION]
                        [--min-runs N] [--min-classifiers N] [--min-categorizers N]
                        [--moving] [--out-of-range] [--max-interval D]
                        [--time-out D] [--profile NAME]

Each TABLE carries a DataQuality action with a ``Summary`` and a ``SummaryTrend``:
every version of ``<TABLE>_dq_summary`` (one row per classifier) is folded by the
server's trend function into ``<TABLE>_dq_summary_trends``, which holds a ``run`` row
per classifier and summary version, ``week`` and ``month`` rows summing those, and one
``folded`` row per transaction already counted. The project is ``$XP_PROJECT``; the
files this reads are left under ``$XP_WORK_DIR/dq-trends/COLLECTION/``.

The trend function runs after the summary it reads, so the latest trend may still be
a summary or two behind: each table is polled until its latest trend has a ``run``
row for every summary version of every boolean classifier, and fails at
``--time-out``. Then, per classifier:

- at least ``--min-runs`` run rows: a point per rollover the suite made, each from a
  summary that classified rows -- a run is the publisher's trigger, and every trigger
  must have carried changes;
- the run rows' passed / failed / nulls / nans are the summaries' dq.true / dq.false
  / dq.none / dq.nan, summed -- nothing lost, nothing counted twice;
- the week rows, and the month rows, sum to the run rows (every run counts towards
  its week and month from its first execution), their ``runs`` to the run count;
- one ``folded`` row per transaction the run rows carry;
- ``pass_pct`` is passed / (passed + failed) as a percentage, null when both are 0,
  and every row says the same ``folded_through``;
- with ``--moving``, its ``pass_pct`` differs from one run row to the next, by bucket:
  the data's quality moved, for better or worse, on every run -- every run of new
  data: with ``--cdc``, a run whose input, the latest version of ``<TABLE>_changes``
  at its time, changed no data is let be. The stream commits every table on each
  batch, so its last one -- the sentinel's row alone -- triggers the transformer
  over the rows it classified before, and the summary repeats.

Across the TABLEs, at least ``--min-classifiers`` boolean classifiers (default 1).

A ``--categorized`` TABLE carries ``ScaleCategorizer`` classifiers and a ``Summary``
with no trend (a trend folds boolean classifiers only): its ``<TABLE>_dq_summary`` is
read alone, once its latest version is no older than the latest CDC version of
``<TABLE>_changes`` (with ``--cdc``; else once it has one). Per categorizer:

- at least ``--min-runs`` summary versions carry it, every one from rows classified;
- in each, its bins (``dq.p000`` on), ``dq.under``, ``dq.over``, ``dq.nan`` and
  ``dq.none`` add up to ``dq.total``, and ``dq.bins`` is the same in all;
- with ``--moving``, its histogram, as shares of ``dq.total``, differs from one
  version to the next, a version of an input that changed no data let be as above;
- with ``--out-of-range``, its under- and its overflow are each above 0 in some
  version: the scale's ends are seen.

Across them, at least ``--min-categorizers`` categorizers (default 0).

With ``--cdc COLLECTION``, the stream's own output is checked too: every version of
``<TABLE>_changes`` in it that changed data holds rows (a trigger with nothing to
publish would be an empty batch, which the suite does not configure), and the
versions are ``--max-interval`` apart or less, the median (default 90s): the
publisher triggers once a minute. The first interval -- from the initial load to the
first minute of changes -- is left out, as it waits on the sentinel stage, not the
publisher.

The step's note says each table's runs, the rows its summaries classified and the
intervals between its CDC versions, and for a categorized table the median shift of
its histograms from one version to the next (total variation, 0-1).
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import statistics
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from tdd import TddError, note, tdd  # on the path: xp runs a python step with it

RUN, WEEK, MONTH, FOLDED = "run", "week", "month", "folded"
COUNTS = ("runs", "passed", "failed", "nulls", "nans")
# A summary column -> the trend count it is folded into.
SUMMARY_TO_TREND = {"dq.true": "passed", "dq.false": "failed", "dq.none": "nulls", "dq.nan": "nans"}
POLL_SECS = 10
# A categorizer's bin column, dq.p000 on (dq.parameters is not one).
BIN = re.compile(r"dq\.p\d{3}")

#: `--profile NAME` for every tdk call, or nothing: tdk takes it on each command,
#: after the verb's own options.
PROFILE: list[str] = []


def seconds(text: str) -> float:
    """A suite duration, ``<VALUE><UNIT>`` with unit s, m or h."""
    units = {"s": 1, "m": 60, "h": 3600}
    if not text or text[-1] not in units:
        raise argparse.ArgumentTypeError(f"not a duration (90s, 10m, 1h): {text!r}")
    return float(text[:-1]) * units[text[-1]]


def all_versions(proj: str, coll: str, table: str) -> list[dict]:
    """`table`'s versions, oldest first, as tdk lists them."""
    found = json.loads(
        tdd("tdk", "table", "versions", "--proj", proj, "--coll", coll, "--name", table,
            "--max-result", "0", "--format", "json", *PROFILE)
    )
    return sorted(found, key=lambda v: instant(v.get("created_at")))


def changed_versions(proj: str, coll: str, table: str) -> list[dict]:
    """`table`'s versions that changed data, oldest first."""
    return [v for v in all_versions(proj, coll, table) if v.get("data_changed")]


class Inputs:
    """A table's CDC versions, to tell a run of new data from a run over an input
    version that changed none. A version a function writes carries its trigger's
    ``created_at``; the trend's bucket is the summary's commit, a little later and
    a batch before the next one."""

    def __init__(self, found: list[dict]) -> None:
        self.found = [(instant(v.get("created_at")), bool(v.get("data_changed"))) for v in found]

    def unchanged(self, at: float) -> bool:
        """Whether the latest input version at `at` changed no data."""
        before = [changed for t, changed in self.found if t <= at]
        return bool(before) and not before[-1]


def versions(proj: str, coll: str, table: str) -> list[str]:
    """The ids of `table`'s versions that changed data, oldest first."""
    return [v["id"] for v in changed_versions(proj, coll, table)]


def instant(value) -> float:
    """A version's ``created_at`` as epoch seconds: a number (milliseconds past
    1e11, seconds below) or an ISO 8601 string."""
    if value in (None, ""):
        return 0.0
    if isinstance(value, (int, float)) or str(value).isdigit():
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()


def cdc_cadence(proj: str, coll: str, table: str, max_interval: float) -> tuple[list[str], str]:
    """Problems with `table`'s CDC versions -- one that holds no rows, a median
    interval past `max_interval` -- and the figure for the note."""
    found = changed_versions(proj, coll, f"{table}_changes")
    problems = [
        f"{table}_changes: version {v['id']} changed data with {v.get('row_count')} row(s)"
        for v in found
        if v.get("row_count") is not None and int(v["row_count"]) < 1
    ]
    times = [instant(v.get("created_at")) for v in found]
    gaps = [b - a for a, b in zip(times[1:], times[2:])]  # the load's wait left out
    if not gaps:
        return problems + [f"{table}_changes: {len(found)} version(s), no interval to measure"], ""
    mid = statistics.median(gaps)
    if mid > max_interval:
        problems.append(f"{table}_changes: versions a median {mid:.0f}s apart, past {max_interval:g}s")
    return problems, f"{len(found)} cdc versions {min(gaps):.0f}/{mid:.0f}/{max(gaps):.0f}s apart"


def rows(proj: str, coll: str, table: str, version: str, work: Path) -> list[dict]:
    """One version's rows, every value a string (empty for null). A version that
    holds no data writes no file, and has no rows."""
    f = work / f"{table}.{version}.parquet"
    if not f.exists():
        tdd("tdk", "table", "download", "--proj", proj, "--coll", coll, "--name", table,
            "--version", version, "--file", str(f), *PROFILE)
    if not f.exists():
        return []
    return list(csv.DictReader(tdd("pqt", "csv", str(f)).splitlines()))


def num(value: str) -> float:
    return float(value) if value not in ("", None) else 0.0


class Summaries:
    """Every version of a summary table, read once each: per boolean classifier, how
    many versions carry it and its tallies summed; per categorizer, its row in each
    version, oldest first; the rows classified; and when the latest was made."""

    def __init__(self) -> None:
        self.read: set[str] = set()
        self.runs: dict[str, int] = defaultdict(int)
        self.sums: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))
        self.categories: dict[str, list[tuple[str, float, dict]]] = defaultdict(list)
        self.classified = 0
        self.empty: list[str] = []
        self.latest = 0.0

    def update(self, proj: str, coll: str, table: str, work: Path) -> None:
        for found in changed_versions(proj, coll, table):
            v = found["id"]
            if v in self.read:
                continue
            got = rows(proj, coll, table, v, work)
            self.read.add(v)
            at = instant(found.get("created_at"))
            self.latest = max(self.latest, at)
            # dq.total is the rows the action saw, on every classifier's row alike.
            total = int(max((num(r.get("dq.total", "")) for r in got), default=0))
            if total < 1:
                self.empty.append(v)
            self.classified += total
            for r in got:
                if r.get("dq.type") == "categorical":
                    self.categories[r["dq.classifier"]].append((v, at, r))
                if r.get("dq.type") != "boolean":
                    continue
                c = r["dq.classifier"]
                self.runs[c] += 1
                for src, dst in SUMMARY_TO_TREND.items():
                    self.sums[c][dst] += num(r.get(src, ""))


def latest_trend(proj: str, coll: str, table: str, work: Path) -> list[dict]:
    found = versions(proj, coll, table)
    return rows(proj, coll, table, found[-1], work) if found else []


def behind(summaries: Summaries, trend: list[dict]) -> dict[str, tuple[int, int]]:
    """The classifiers whose run rows have not caught up: {classifier: (have, want)}."""
    have: dict[str, int] = defaultdict(int)
    for r in trend:
        if r["grain"] == RUN:
            have[r["classifier"]] += 1
    return {c: (have[c], n) for c, n in summaries.runs.items() if have[c] != n}


def check(
    table: str,
    summaries: Summaries,
    trend: list[dict],
    min_runs: int,
    moving: bool = False,
    inputs: Inputs | None = None,
) -> list[str]:
    problems = []
    if moving:
        series: dict[str, list[tuple[str, str]]] = defaultdict(list)
        for r in sorted((r for r in trend if r["grain"] == RUN), key=lambda r: r["bucket"]):
            series[r["classifier"]].append((r["bucket"], r["pass_pct"]))
        for c, points in series.items():
            still = [
                b for (_, a), (b, x) in zip(points, points[1:])
                if a == x and not (inputs and inputs.unchanged(instant(b)))
            ]
            if still:
                problems.append(f"{table}: {c} pass_pct did not move into {len(still)} run(s): {still[:3]}")
    by_grain: dict[str, dict[str, dict[str, float]]] = {
        g: defaultdict(lambda: defaultdict(float)) for g in (RUN, WEEK, MONTH)
    }
    run_txns: set[str] = set()
    folded_txns: list[str] = []
    for r in trend:
        g = r["grain"]
        if g == FOLDED:
            folded_txns.append(r["txn"])
            continue
        if g not in by_grain:
            problems.append(f"{table}: a row of grain {g!r}")
            continue
        for k in COUNTS:
            by_grain[g][r["classifier"]][k] += num(r[k])
        if g == RUN:
            run_txns.add(r["txn"])
        passed, failed = num(r["passed"]), num(r["failed"])
        if passed + failed == 0:
            if r["pass_pct"] not in ("", None):
                problems.append(f"{table}: {g} {r['classifier']} pass_pct {r['pass_pct']} with nothing passed or failed")
        elif abs(num(r["pass_pct"]) - passed * 100.0 / (passed + failed)) > 1e-6:
            problems.append(f"{table}: {g} {r['classifier']} pass_pct {r['pass_pct']} for {passed:g}/{failed:g}")
    if summaries.empty:
        problems.append(f"{table}: {len(summaries.empty)} summary version(s) classified no rows: {summaries.empty}")
    marks = {r["folded_through"] for r in trend}
    if len(marks) != 1:
        problems.append(f"{table}: folded_through differs across rows: {sorted(marks)}")
    if sorted(folded_txns) != sorted(run_txns):
        problems.append(
            f"{table}: {len(folded_txns)} folded row(s) ({len(set(folded_txns))} distinct) "
            f"for {len(run_txns)} transaction(s) in the run rows"
        )
    for c, want in summaries.sums.items():
        runs = by_grain[RUN][c]
        if runs["runs"] < min_runs:
            problems.append(f"{table}: {c} has {runs['runs']:g} run row(s), fewer than {min_runs}")
        for k, v in want.items():
            if runs[k] != v:
                problems.append(f"{table}: {c} run rows' {k} sum to {runs[k]:g}, the summaries' to {v:g}")
        for g in (WEEK, MONTH):
            for k in COUNTS:
                if by_grain[g][c][k] != runs[k]:
                    problems.append(f"{table}: {c} {g} rows' {k} sum to {by_grain[g][c][k]:g}, the run rows' to {runs[k]:g}")
    return problems


def histogram(r: dict) -> tuple[list[float], float]:
    """A categorizer's summary row as counts -- under, over, nan, none, then every
    bin column it fills -- and its dq.total."""
    bins = sorted(k for k in r if BIN.fullmatch(k) and r[k] not in ("", None))
    return [num(r[k]) for k in ("dq.under", "dq.over", "dq.nan", "dq.none", *bins)], num(r["dq.total"])


def check_categories(
    table: str,
    summaries: Summaries,
    min_runs: int,
    moving: bool,
    out_of_range: bool,
    inputs: Inputs | None = None,
) -> tuple[list[str], list[float]]:
    """Problems with `table`'s categorizers, and every shift of a histogram from one
    version to the next (total variation)."""
    problems, shifts = [], []
    if summaries.empty:
        problems.append(f"{table}: {len(summaries.empty)} summary version(s) classified no rows: {summaries.empty}")
    for c, found in sorted(summaries.categories.items()):
        if len(found) < min_runs:
            problems.append(f"{table}: {c} is in {len(found)} summary version(s), fewer than {min_runs}")
        if len({r["dq.bins"] for _, _, r in found}) != 1:
            problems.append(f"{table}: {c} dq.bins differs across versions: {sorted({r['dq.bins'] for _, _, r in found})}")
        previous = None
        for v, at, r in found:
            counts, total = histogram(r)
            if sum(counts) != total:
                problems.append(f"{table}: {c} version {v} counts {sum(counts):g} rows of a dq.total of {total:g}")
            shares = [x / total for x in counts] if total else counts
            if previous is not None and len(previous) == len(shares):
                if inputs and inputs.unchanged(at):
                    continue  # the same rows again: neither a shift nor a stall
                shift = sum(abs(a - b) for a, b in zip(previous, shares)) / 2
                shifts.append(shift)
                if moving and shift == 0:
                    problems.append(f"{table}: {c} histogram did not move into version {v}")
            previous = shares
        if out_of_range:
            for end in ("dq.under", "dq.over"):
                if not any(num(r[end]) > 0 for _, _, r in found):
                    problems.append(f"{table}: {c} has no {end} in any version")
    return problems, shifts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("collection")
    parser.add_argument("tables", nargs="+", metavar="TABLE")
    parser.add_argument("--categorized", action="append", default=[], metavar="TABLE",
                        help="a table whose summary carries categorizers and no trend; repeatable")
    parser.add_argument("--min-runs", type=int, default=1, help="run rows each classifier must have (default 1)")
    parser.add_argument("--min-classifiers", type=int, default=1,
                        help="boolean classifiers the TABLEs must carry between them (default 1)")
    parser.add_argument("--min-categorizers", type=int, default=0,
                        help="categorizers the --categorized TABLEs must carry between them (default 0)")
    parser.add_argument("--moving", action="store_true",
                        help="every classifier's pass_pct, every categorizer's histogram, "
                             "must change from one run to the next")
    parser.add_argument("--out-of-range", action="store_true",
                        help="every categorizer must see an underflow and an overflow")
    parser.add_argument("--cdc", metavar="COLLECTION",
                        help="the stream publisher's collection, holding <TABLE>_changes: check its cadence")
    parser.add_argument("--max-interval", type=seconds, default=seconds("90s"),
                        help="the median interval allowed between CDC versions (default 90s)")
    parser.add_argument("--time-out", type=seconds, default=seconds("10m"),
                        help="how long the trends may take to catch up with the summaries (default 10m)")
    parser.add_argument("--profile", default=None, metavar="NAME",
                        help="the tdk connection to read on; empty or absent: tdk's default")
    args = parser.parse_args()
    if args.profile:
        PROFILE[:] = ["--profile", args.profile]
    proj, coll = os.environ["XP_PROJECT"], args.collection
    work = Path(os.environ["XP_WORK_DIR"]) / "dq-trends" / coll
    work.mkdir(parents=True, exist_ok=True)

    problems, figures, classifiers = [], [], 0
    deadline = time.monotonic() + args.time_out
    for table in args.tables:
        summaries = Summaries()
        while True:
            summaries.update(proj, coll, f"{table}_dq_summary", work)
            trend = latest_trend(proj, coll, f"{table}_dq_summary_trends", work)
            lag = behind(summaries, trend)
            if summaries.runs and not lag:
                break
            if time.monotonic() > deadline:
                problems.append(
                    f"{table}: the trend did not catch up in {args.time_out:g}s -- "
                    + (", ".join(f"{c} {h}/{w} run row(s)" for c, (h, w) in sorted(lag.items()))
                       or "no summary version")
                )
                trend = None
                break
            time.sleep(POLL_SECS)
        if trend is None:
            continue
        print(f"{table}: {len(summaries.read)} summary version(s), {len(trend)} trend row(s)")
        inputs = Inputs(all_versions(proj, args.cdc, f"{table}_changes")) if args.cdc else None
        problems += check(table, summaries, trend, args.min_runs, args.moving, inputs)
        classifiers += len(summaries.runs)
        figure = f"{table} {min(summaries.runs.values())} runs {summaries.classified} rows"
        if args.cdc:
            cadence_problems, cadence = cdc_cadence(proj, args.cdc, table, args.max_interval)
            problems += cadence_problems
            figure += f", {cadence}" if cadence else ""
        figures.append(figure)

    categorizers = 0
    for table in args.categorized:
        summaries = Summaries()
        while True:
            summaries.update(proj, coll, f"{table}_dq_summary", work)
            want = 0.0
            if args.cdc:
                found = changed_versions(proj, args.cdc, f"{table}_changes")
                want = instant(found[-1].get("created_at")) if found else 0.0
            if summaries.categories and summaries.latest >= want:
                break
            if time.monotonic() > deadline:
                problems.append(f"{table}: the summary did not catch up with the stream in {args.time_out:g}s")
                summaries = None
                break
            time.sleep(POLL_SECS)
        if summaries is None:
            continue
        print(f"{table}: {len(summaries.read)} summary version(s), {len(summaries.categories)} categorizer(s)")
        inputs = Inputs(all_versions(proj, args.cdc, f"{table}_changes")) if args.cdc else None
        found_problems, shifts = check_categories(
            table, summaries, args.min_runs, args.moving, args.out_of_range, inputs
        )
        problems += found_problems
        categorizers += len(summaries.categories)
        figure = (
            f"{table} {min(len(f) for f in summaries.categories.values())} runs "
            f"{summaries.classified} rows, histograms shift a median "
            f"{statistics.median(shifts) if shifts else 0:.2f}"
        )
        if args.cdc:
            cadence_problems, cadence = cdc_cadence(proj, args.cdc, table, args.max_interval)
            problems += cadence_problems
            figure += f", {cadence}" if cadence else ""
        figures.append(figure)

    if classifiers < args.min_classifiers:
        problems.append(f"{classifiers} classifier(s) across {', '.join(args.tables)}, fewer than {args.min_classifiers}")
    if categorizers < args.min_categorizers:
        problems.append(
            f"{categorizers} categorizer(s) across {', '.join(args.categorized) or 'no table'}, "
            f"fewer than {args.min_categorizers}"
        )
    note(f"{classifiers} classifiers, {categorizers} categorizers; " + "; ".join(figures))
    for p in problems:
        print(p, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TddError as e:
        print(e, file=sys.stderr)
        sys.exit(1)
