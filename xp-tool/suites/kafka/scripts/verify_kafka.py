#
# Copyright 2026 Tabsdata Inc.
#
"""Check Kafka stream publishers' tables against the messages a domain was sent.

    verify_kafka.py OPS_FILE COLLECTION --expect TABLE[+TABLE...]=ENTITY ...
                    [--empty TABLE ...] [--dead [COLLECTION/]TABLE [--require-dead]]
                    [--allow-duplicates] [--time-out DURATION]

OPS_FILE is the trail ``tdd domain create-data/modify-data --emit-ops``
appended: on a redpanda domain one insert line per message, its ``row`` the
message as produced -- ``--schema-changes`` rows as they were varied. The
tables are COLLECTION's, in project ``$XP_PROJECT``; what this reads is left
under ``$XP_WORK_DIR/kafka/COLLECTION/``.

``--expect T=E`` says table T holds topic E's messages; ``T1+T2=E`` that
those tables between them do -- two publishers in one consumer group, each
reading the partitions the group gave it. Every message of E in the trail must
be in one of them, or in the dead-letter table, exactly once; a row nobody sent
is a problem, and so is a message arriving twice, unless
``--allow-duplicates``: Kafka delivers at least once, and a partition a
rebalance hands over before its offsets were committed is read again by its new
owner. ``--empty T`` says T holds no row at all: a topic subscribed to and
never written, or the frames a router could not place.

``--dead T`` is the table a publisher of the dead-letter topic writes: each
row an envelope whose ``original_value`` is the refused message and ``topic``
the topic it came from. Its messages count as arrived; ``--require-dead``
fails a run in which none was refused -- a suite sending rows a schema must
refuse checks that it did.

Rows compare on the union of the columns the table and the trail know of, a
missing field as null: a message left without its last field arrives with that
column null, and a table folding frames that differ (``diagonal_relaxed``)
gives every row every column. Values compare as text, as the CDC check's do.

A publisher stages a batch when its trigger fires, so the check polls: every
version that changed data is read once, and the tables are read again every
10s until every message has arrived or ``--time-out`` (default 5m) has passed.
Exit 0 when everything holds, 1 with what differs.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tdd import TddError, note, tdd  # on the path: xp runs a python step with it

POLL_SECONDS = 10
_DURATION = re.compile(r"^(\d+(?:\.\d+)?)([smh])$")
_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?)?$")


def seconds(text: str) -> float:
    m = _DURATION.match(text.strip())
    if not m:
        raise argparse.ArgumentTypeError(f"not a duration (<VALUE><s|m|h>): {text!r}")
    return float(m.group(1)) * {"s": 1, "m": 60, "h": 3600}[m.group(2)]


def norm(v) -> str | None:
    """A value as both sides agree on it: the trail has JSON, a table's CSV
    text (an empty field for null, a space before a time)."""
    if v is None:
        return None
    if isinstance(v, (list, dict)):
        return json.dumps(v, sort_keys=True)
    s = str(v).strip()
    if s == "":
        return None
    if s.startswith("[") or s.startswith("{"):
        try:
            return json.dumps(json.loads(s), sort_keys=True)
        except json.JSONDecodeError:
            return s
    m = _WHEN.match(s)
    if m:
        date, clock, frac = m.groups()
        frac = (frac or "").rstrip("0")
        return date if not clock else f"{date} {clock}" + (f".{frac}" if frac else "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return s
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def user_columns(row: dict) -> dict:
    """`row` without tabsdata's own columns (``@td.kafka.topic`` and the like)."""
    return {k: v for k, v in row.items() if not (k.startswith("@td.") or k.startswith("$td."))}


class Table:
    """One table's rows, every version that changed data read once."""

    def __init__(self, proj: str, coll: str, name: str, work: Path):
        self.proj, self.coll, self.name, self.work = proj, coll, name, work
        self.read: set[str] = set()
        self.rows: list[dict] = []
        self.error = ""

    def refresh(self) -> None:
        try:
            versions = json.loads(
                tdd("tdk", "table", "versions", "--proj", self.proj, "--coll", self.coll,
                    "--name", self.name, "--max-result", "0", "--format", "json")
            )
        except (TddError, json.JSONDecodeError) as exc:
            # A table no flush has written to yet may not answer; said if it lasts.
            self.error = str(exc).splitlines()[0]
            return
        self.error = ""
        changed = sorted(
            (v for v in versions if v.get("data_changed") and v["id"] not in self.read),
            key=lambda v: v.get("created_at") or 0,
        )
        for v in changed:
            f = self.work / f"{self.coll}.{self.name}.{v['id']}.parquet"
            tdd("tdk", "table", "download", "--proj", self.proj, "--coll", self.coll,
                "--name", self.name, "--version", v["id"], "--file", str(f))
            text = tdd("pqt", "csv", str(f))
            self.rows.extend(user_columns(r) for r in csv.DictReader(text.splitlines()))
            self.read.add(v["id"])

    @property
    def columns(self) -> set[str]:
        return {c for r in self.rows for c in r}


def table_ref(text: str, coll: str) -> tuple[str, str]:
    c, sep, t = text.partition("/")
    return (c, t) if sep else (coll, text)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("ops_file", type=Path)
    parser.add_argument("collection")
    parser.add_argument("--expect", action="append", default=[], metavar="TABLE[+TABLE...]=ENTITY",
                        help="these tables hold ENTITY's messages between them")
    parser.add_argument("--empty", nargs="+", default=[], metavar="TABLE",
                        help="tables that must hold no row")
    parser.add_argument("--dead", metavar="[COLLECTION/]TABLE",
                        help="the dead-letter envelopes' table; its messages count as arrived")
    parser.add_argument("--require-dead", action="store_true",
                        help="fail when no message was refused to the dead-letter topic")
    parser.add_argument("--allow-duplicates", action="store_true",
                        help="a message arriving more than once is noted, not a problem")
    parser.add_argument("--time-out", type=seconds, default=seconds("5m"), metavar="DURATION")
    args = parser.parse_args()
    if args.require_dead and not args.dead:
        parser.error("--require-dead needs --dead")
    expects = []
    for spec in args.expect:
        tables, sep, entity = spec.partition("=")
        if not sep or not entity or not tables:
            parser.error(f"--expect: not TABLE[+TABLE...]=ENTITY: {spec!r}")
        expects.append((tables.split("+"), entity))
    if not expects and not args.empty:
        parser.error("nothing to check: give --expect or --empty")

    proj = os.environ["XP_PROJECT"]
    work = Path(os.environ["XP_WORK_DIR"]) / "kafka" / args.collection
    work.mkdir(parents=True, exist_ok=True)

    trail = [json.loads(x) for x in args.ops_file.read_text(encoding="utf-8").splitlines() if x.strip()]
    sent: dict[str, list[dict]] = {}
    for o in trail:
        if not o.get("dry_run") and o.get("op") == "insert":
            sent.setdefault(o["entity"], []).append(o["row"])

    tables: dict[tuple[str, str], Table] = {}

    def table(ref: tuple[str, str]) -> Table:
        if ref not in tables:
            tables[ref] = Table(proj, ref[0], ref[1], work)
        return tables[ref]

    groups = [([table((args.collection, t)) for t in names], entity) for names, entity in expects]
    empties = [table((args.collection, t)) for t in args.empty]
    dead = table(table_ref(args.dead, args.collection)) if args.dead else None

    def dead_letters() -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for r in dead.rows if dead else []:
            try:
                message = json.loads(r.get("original_value") or "")
            except json.JSONDecodeError:
                message = {"original_value": r.get("original_value")}
            entity = (r.get("topic") or "").rsplit(".", 1)[-1]
            out.setdefault(entity, []).append(message if isinstance(message, dict) else {"value": message})
        return out

    def evaluate():
        problems, noted = [], []
        letters = dead_letters()
        missing_total = 0
        for group, entity in groups:
            expected_rows = sent.get(entity, [])
            got_rows = [r for t in group for r in t.rows]
            refused = letters.get(entity, [])
            cols = sorted({c for r in expected_rows for c in r} | {c for t in group for c in t.columns})

            def canon(row: dict) -> tuple:
                return tuple(norm(row.get(c)) for c in cols)

            expected = Counter(canon(r) for r in expected_rows)
            arrived = Counter(canon(r) for r in got_rows) + Counter(canon(r) for r in refused)
            missing = expected - arrived
            extra = arrived - expected
            names = "+".join(t.name for t in group)
            missing_total += sum(missing.values())
            if missing:
                problems.append(f"{names}: {sum(missing.values())} of the {sum(expected.values())} {entity} message(s) never arrived, e.g. {dict(zip(cols, next(iter(missing))))}")
            unsent = Counter({k: n for k, n in extra.items() if k not in expected})
            again = extra - unsent
            if unsent:
                problems.append(f"{names}: {sum(unsent.values())} row(s) no message of {entity} was, e.g. {dict(zip(cols, next(iter(unsent))))}")
            if again:
                line = f"{names}: {sum(again.values())} message(s) of {entity} arrived more than once"
                (noted if args.allow_duplicates else problems).append(line)
            if len(group) > 1:
                noted.append(f"{names}: " + ", ".join(f"{t.name} {len(t.rows)}" for t in group))
        for t in empties:
            if t.rows:
                problems.append(f"{t.name}: {len(t.rows)} row(s) in a table that must stay empty, e.g. {t.rows[0]}")
        refused_total = sum(len(v) for v in letters.values())
        if args.require_dead and refused_total == 0:
            problems.append(f"{dead.name}: no message was refused to the dead-letter topic")
        return problems, noted, missing_total, refused_total

    deadline = time.monotonic() + args.time_out
    while True:
        for t in tables.values():
            t.refresh()
        problems, noted, missing, refused = evaluate()
        if missing == 0 and not (args.require_dead and refused == 0):
            break
        if time.monotonic() >= deadline:
            # A table that must stay empty may never have been written at all.
            stuck = [f"{t.name}: {t.error}" for t in tables.values() if t.error and t not in empties]
            problems += [f"timed out after {args.time_out:.0f}s; last read errors: {s}" for s in stuck]
            break
        time.sleep(POLL_SECONDS)

    rows = sum(len(t.rows) for t in tables.values() if t is not dead)
    summary = f"{rows} row(s) in {len(tables) - (1 if dead else 0)} table(s), {refused} dead letter(s)"
    (work / "report.txt").write_text(
        summary + "\n" + "".join(f"  {p}\n" for p in problems) + "".join(f"  noted: {n}\n" for n in noted),
        encoding="utf-8",
    )
    print(summary)
    for line in problems + [f"noted: {n}" for n in noted]:
        print(f"  {line}")
    note(summary + (f", {len(problems)} problem(s)" if problems else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TddError as exc:  # a tool that failed ends the check with what it said
        sys.exit(str(exc))
