#
# Copyright 2026 Tabsdata Inc.
#
"""Check a CDC stream's output against the operations the domain was given.

    verify_cdc_ops.py OPS_FILE COLLECTION

OPS_FILE is the trail ``tdd domain create-data/modify-data/sentinel-data
--emit-ops`` appended, one JSON line per operation, in the order the operations
were applied. COLLECTION holds the stream publisher's output, one
``<entity>_changes`` table per source table. The project is ``$XP_PROJECT``;
every file this makes goes under ``$XP_WORK_DIR/cdc/``, left there to read.

For each table: ``tdd-exe tdk table versions`` lists its versions, and each
version that changed data is downloaded (``tdk table download``) and turned into
CSV (``parquet-tools csv``) -- a version whose data did not change repeats the
one before it, so reading it would count its rows twice. Each table's rows become
``<table>.ops.jsonl``; all tables' together, in order, ``actual.jsonl``.

The stream's output is two things. The initial load is a snapshot: the tables'
STATE when the stream started, every row an insert, in no order worth keeping.
Everything after it is changes, grouped by source transaction and ordered by
the position in it. So the last N transactions of OPS_FILE, N being how many
source transactions the stream delivered, pair with those one to one: each of the
trail's operations must appear in its source transaction, in order -- operation,
table, key and values. A source transaction may carry more than the trail says,
but only deletes: the rows an ON DELETE CASCADE took with the one the trail
deleted, which the database did and no command asked for. They are counted and
listed, not refused. The transactions before those N, replayed, must leave
exactly the snapshot's rows in each table. Exit 0 when both hold, 1 with what
differs otherwise.
"""

from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

OLD = "@td.cdc.data.col.old."
OP = "@td.cdc.meta.op"
TX = "@td.cdc.meta.tx"
SQ = "@td.cdc.meta.sq"
LOAD_TX = "initial-load"
_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?)?$")


def run(*argv: str) -> str:
    """One command, its stdout; a failure ends the check with what it said."""
    r = subprocess.run(argv, capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"{' '.join(argv)} exited {r.returncode}:\n{r.stderr or r.stdout}")
    return r.stdout


def norm(v) -> str | None:
    """A value as both sides can agree on it: the trail has JSON (ISO dates,
    Decimals as strings), the stream CSV (a space before the time, microseconds,
    a decimal's scale, an empty field for null)."""
    if v is None:
        return None
    s = str(v).strip()
    if s == "":
        return None
    if s.lower() in ("true", "false"):
        return s.lower()
    m = _WHEN.match(s)
    if m:
        date, clock, frac = m.groups()
        if not clock:
            return date
        frac = (frac or "").rstrip("0")
        return f"{date} {clock}" + (f".{frac}" if frac else "")
    try:
        d = Decimal(s)
    except InvalidOperation:
        return s
    return str(int(d)) if d == d.to_integral_value() else str(d.normalize())


def stream_rows(project: str, coll: str, table: str, out: Path) -> list[dict]:
    """Every row the stream wrote to `table`, version by version, oldest first."""
    where = ["--proj", project, "--coll", coll, "--name", table]
    versions = json.loads(
        run("tdd-exe", "tdk", "table", "versions", *where, "--max-result", "0", "--format", "json")
    )
    changed = [v for v in versions if v.get("data_changed")]
    changed.sort(key=lambda v: v.get("created_at") or 0)
    rows: list[dict] = []
    for n, v in enumerate(changed):
        stem = out / f"{table}.{n:03d}.{v['id']}"
        run("tdd-exe", "tdk", "table", "download", *where, "--version", v["id"], "--file", f"{stem}.parquet")
        text = run("parquet-tools", "csv", f"{stem}.parquet")
        Path(f"{stem}.csv").write_text(text, encoding="utf-8")
        rows += list(csv.DictReader(text.splitlines()))
    return rows


def as_op(entity: str, row: dict) -> dict:
    """A stream row in the trail's shape: ``op``, ``entity``, then ``row`` (the
    new values) and ``old`` (the before-image), plus the source tx and seq."""
    # `@td.` is the connector's metadata, `$td.` the system's own columns.
    new = {k: v for k, v in row.items() if not k.startswith(("@td.", "$td."))}
    old = {k[len(OLD) :]: v for k, v in row.items() if k.startswith(OLD)}
    op = {"i": "insert", "u": "update", "d": "delete"}.get(row.get(OP, ""), row.get(OP))
    if op == "delete" and not any(old.values()):
        # A delete carries the row it removed in the data columns and leaves the
        # before-image empty: the row is its before-image.
        old = new
    return {
        "op": op,
        "entity": entity,
        "tx": row.get(TX),
        "sq": int(row.get(SQ) or 0),
        "row": new,
        "old": old,
    }


def matches(exp: dict, got: dict) -> str | None:
    """Why `got` (a stream change) is not `exp` (a trail operation), or None."""
    if (exp["op"], exp["entity"]) != (got["op"], got["entity"]):
        return f"expected {exp['op']} on {exp['entity']}, got {got['op']} on {got['entity']}"
    if exp["op"] == "insert":
        wrong = [c for c, v in exp["row"].items() if norm(v) != norm(got["row"].get(c))]
        return f"insert values differ in {wrong}" if wrong else None
    wrong = [c for c, v in exp["key"].items() if norm(v) != norm(got["old"].get(c))]
    if wrong:
        return f"{exp['op']} of another row: key {exp['key']} vs before-image {got['old']}"
    if exp["op"] == "update":
        wrong = [c for c, v in exp["set"].items() if norm(v) != norm(got["row"].get(c))]
        return f"update values differ in {wrong}" if wrong else None
    return None


def replay(ops: list[dict]) -> dict[str, list[tuple]]:
    """The rows `ops` leave in each table, as sorted normalized tuples. A row is
    known by the columns updates and deletes name it by; a table only ever
    inserted into is known by the whole row."""
    keys: dict[str, list[str]] = {}
    for o in ops:
        if "key" in o:
            keys.setdefault(o["entity"], list(o["key"]))
    state: dict[str, dict] = {}
    for o in ops:
        t = state.setdefault(o["entity"], {})
        cols = keys.get(o["entity"])
        if o["op"] == "insert":
            pk = tuple(norm(o["row"][c]) for c in cols) if cols else tuple(sorted(o["row"].items()))
            t[pk] = dict(o["row"])
        else:
            pk = tuple(norm(o["key"][c]) for c in cols)
            if o["op"] == "delete":
                t.pop(pk, None)
            elif pk in t:
                t[pk].update(o["set"])
    return {e: sorted(tuple((c, norm(v)) for c, v in sorted(r.items())) for r in t.values()) for e, t in state.items()}


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2])
    ops_file, coll = Path(sys.argv[1]), sys.argv[2]
    project = os.environ["XP_PROJECT"]
    out = Path(os.environ["XP_WORK_DIR"]) / "cdc"
    out.mkdir(parents=True, exist_ok=True)

    trail = [json.loads(line) for line in ops_file.read_text(encoding="utf-8").splitlines() if line.strip()]
    trail = [o for o in trail if not o.get("dry_run")]
    entities = list(dict.fromkeys(o["entity"] for o in trail))

    snapshot: dict[str, list[dict]] = {}
    changes: list[dict] = []
    for entity in entities:
        table = f"{entity}_changes"
        stream = [as_op(entity, r) for r in stream_rows(project, coll, table, out)]
        stream = [s for s in stream if s["op"] in ("insert", "update", "delete")]  # LOAD rows are markers
        (out / f"{table}.ops.jsonl").write_text("".join(json.dumps(s) + "\n" for s in stream), encoding="utf-8")
        snapshot[entity] = [s["row"] for s in stream if s["tx"] == LOAD_TX]
        changes += [s for s in stream if s["tx"] != LOAD_TX]
    changes.sort(key=lambda s: (int(s["tx"]), s["sq"]))
    (out / "actual.jsonl").write_text("".join(json.dumps(s) + "\n" for s in changes), encoding="utf-8")

    problems: list[str] = []
    # The trail's transactions: one run of one verb numbers its own from 0.
    trail_txns: dict[tuple, list[dict]] = {}
    for o in trail:
        trail_txns.setdefault((o["ts"], o["domain"], o["verb"], o["txn"]), []).append(o)
    source_txns: dict[str, list[dict]] = {}
    for c in changes:
        source_txns.setdefault(c["tx"], []).append(c)
    exp_groups, got_groups = list(trail_txns.values()), list(source_txns.values())
    if len(got_groups) > len(exp_groups):
        problems.append(
            f"the stream delivered {len(got_groups)} source transactions, the trail has only "
            f"{len(exp_groups)}"
        )
    split = max(0, len(exp_groups) - len(got_groups))
    before = [o for g in exp_groups[:split] for o in g]

    # The snapshot: the trail up to the split, replayed, is each table's state.
    want = replay(before)
    for entity in entities:
        cols = {c for r in [o["row"] for o in trail if o["entity"] == entity and o["op"] == "insert"][:1] for c in r}
        got = sorted(
            tuple((c, norm(v)) for c, v in sorted(r.items()) if c in cols) for r in snapshot.get(entity, [])
        )
        if got != want.get(entity, []):
            problems.append(
                f"snapshot of {entity}: {len(got)} row(s), the {len(before)} operation(s) before it "
                f"leave {len(want.get(entity, []))}"
            )

    # The changes: transaction by transaction, the trail's operations in order
    # within each, anything more a cascaded delete.
    cascaded: list[str] = []
    for exp_ops, got_ops in zip(exp_groups[split:], got_groups):
        what = f"{exp_ops[0]['verb']} txn {exp_ops[0]['txn']} (source tx {got_ops[0]['tx']})"
        i = 0
        for got in got_ops:
            exp = exp_ops[i] if i < len(exp_ops) else None
            if exp is not None and matches(exp, got) is None:
                i += 1
            elif exp is not None and got["op"] != "delete" and (exp["op"], exp["entity"]) == (
                got["op"],
                got["entity"],
            ):
                # The operation the trail expected, with the wrong values: said
                # once, and the pairing moves on rather than failing every one after.
                problems.append(f"{what}: {matches(exp, got)}")
                i += 1
            elif got["op"] == "delete":
                cascaded.append(f"{what}: delete on {got['entity']} {got['old']}")
            else:
                why = matches(exp_ops[i], got) if i < len(exp_ops) else "nothing more was expected"
                problems.append(f"{what}: unexpected {got['op']} on {got['entity']}: {why}")
        for exp in exp_ops[i:]:
            problems.append(f"{what}: {exp['op']} on {exp['entity']} never arrived")

    summary = (
        f"{len(trail)} operation(s) in the trail: {len(before)} in the snapshot, "
        f"{len(trail) - len(before)} as {len(got_groups)} source transaction(s) of changes "
        f"({len(cascaded)} cascaded delete(s) beside them), over {len(entities)} table(s)"
    )
    (out / "report.txt").write_text(
        summary
        + "\n"
        + "".join(f"  {p}\n" for p in problems)
        + "".join(f"  cascaded: {c}\n" for c in cascaded),
        encoding="utf-8",
    )
    print(summary)
    for p in problems[:20]:
        print(f"  {p}")
    if len(problems) > 20:
        print(f"  ... {len(problems) - 20} more in {out / 'report.txt'}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
