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

The work is files through tools, each step one function (see ``main``):

    get_table_versions  tdd tdk table versions   the versions that changed data
    get_table_data      tdd tdk table download   one parquet per version
    convert_parquet_to_json  tdd pqt csv         one JSON line per row
    to_ops              tdd jq                   rows -> the trail's shape, in order
    concat                                       files -> one file

A version whose data did not change repeats the one before it, so only the
versions that changed are read. The stream's output is two things. The initial
load is a snapshot: the tables' STATE when the stream started, every row an
insert, in no order worth keeping. Everything after it is changes, grouped by
source transaction and ordered by the position in it. So the last N transactions
of OPS_FILE, N being how many source transactions the stream delivered, pair
with those one to one: each of the trail's operations must appear in its source
transaction, in order -- operation, table, key and values. A source transaction
may carry more than the trail says, but only deletes: the rows an ON DELETE
CASCADE took with the one the trail deleted, which the database did and no
command asked for. They are counted and listed, not refused. The transactions
before those N, replayed, must leave exactly the snapshot's rows in each table.
Exit 0 when both hold, 1 with what differs otherwise.
"""

from __future__ import annotations

import csv
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tdd import TddError, tdd  # put on the path by `tdd _xp-execute`

LOAD_TX = "initial-load"

# A stream row -> the trail's shape: `op` and `entity`, the source `tx` and `sq`,
# `row` (the new values, the user's columns only) and `old` (the before-image).
# A delete carries the row it removed in the data columns and leaves the
# before-image empty: the row is its before-image. LOAD rows only mark where a
# table's load begins, and go.
_TO_OPS = r"""
  select(.["@td.cdc.meta.op"] != "l")
  | . as $r
  | ($r | with_entries(select(.key | (startswith("@td.") or startswith("$td.")) | not))) as $new
  | ($r | with_entries(select(.key | startswith("@td.cdc.data.col.old."))
                       | .key |= ltrimstr("@td.cdc.data.col.old."))) as $old
  | {"i": "insert", "u": "update", "d": "delete"}[$r["@td.cdc.meta.op"]] as $op
  | {op: $op, entity: $entity, tx: $r["@td.cdc.meta.tx"], sq: ($r["@td.cdc.meta.sq"] | tonumber),
     row: $new,
     old: (if $op == "delete" and ($old | [.[]] | all(. == "")) then $new else $old end)}
"""
# The snapshot first, then the changes by source transaction and position.
_IN_ORDER = r"""sort_by([.tx != "initial-load", (if .tx == "initial-load" then 0 else (.tx | tonumber) end), .sq]) | .[]"""


# ---------------------------------------------------------------- tools ----


def get_table_versions(proj: str, coll: str, table: str) -> list[str]:
    """The ids of `table`'s versions that changed data, oldest first."""
    versions = json.loads(
        tdd("tdk", "table", "versions", "--proj", proj, "--coll", coll, "--name", table,
            "--max-result", "0", "--format", "json")
    )
    changed = sorted((v for v in versions if v.get("data_changed")), key=lambda v: v.get("created_at") or 0)
    return [v["id"] for v in changed]


def get_table_data(proj: str, coll: str, table: str, versions: list[str], work: Path) -> list[Path]:
    """Each version downloaded as a parquet file, in version order."""
    files = []
    for n, version in enumerate(versions):
        f = work / f"{table}.{n:03d}.{version}.parquet"
        tdd("tdk", "table", "download", "--proj", proj, "--coll", coll, "--name", table,
            "--version", version, "--file", str(f))
        files.append(f)
    return files


def convert_parquet_to_json(files: list[Path]) -> list[Path]:
    """Each parquet file as JSON lines, one per row, every value a string (an
    empty one for null). pqt prints CSV and jq reads no CSV, so the CSV is
    parsed here -- quoting and all -- rather than split by hand."""
    out = []
    for f in files:
        text = tdd("pqt", "csv", str(f))
        dest = f.with_suffix(".jsonl")
        dest.write_text("".join(json.dumps(row) + "\n" for row in csv.DictReader(text.splitlines())), encoding="utf-8")
        out.append(dest)
    return out


def to_ops(file: Path, entity: str) -> Path:
    """A table's rows as operations in the trail's shape, snapshot first and
    then the changes in order (jq)."""
    dest = file.with_name(f"{entity}_changes.ops.jsonl")
    ops = tdd("jq", "-c", "--arg", "entity", entity, _TO_OPS, str(file))
    return _jq_sorted(ops, dest)


def concat(files: list[Path], dest: Path) -> Path:
    """`files` one after another, as one file."""
    dest.write_text("".join(f.read_text(encoding="utf-8") for f in files), encoding="utf-8")
    return dest


def in_order(file: Path, dest: Path) -> Path:
    """`file`'s operations, from every table, interleaved in stream order (jq)."""
    return _jq_sorted(file.read_text(encoding="utf-8"), dest)


def _jq_sorted(jsonl: str, dest: Path) -> Path:
    staged = dest.with_suffix(".unsorted.jsonl")
    staged.write_text(jsonl, encoding="utf-8")
    tdd("jq", "-c", "-s", _IN_ORDER, str(staged), out=dest)
    return dest


def read_jsonl(file: Path) -> list[dict]:
    return [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines() if line.strip()]


# ------------------------------------------------------------ comparing ----

_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2})(?:\.(\d+))?)?$")


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
    inserted into is known by the whole row. A delete cascades as the database
    does and the trail does not say: every other table's rows that carry the
    deleted key's columns with its values go too (a foreign key is named as the
    key it references) -- the snapshot of a stream started under changes has
    had those deletes."""
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
                key = {c: norm(v) for c, v in o["key"].items()}
                for entity, rows in state.items():
                    if entity == o["entity"]:
                        continue
                    for rpk, r in list(rows.items()):
                        if all(c in r and norm(r[c]) == v for c, v in key.items()):
                            del rows[rpk]
            elif pk in t:
                t[pk].update(o["set"])
    return {e: sorted(tuple((c, norm(v)) for c, v in sorted(r.items())) for r in t.values()) for e, t in state.items()}


def compare(trail: list[dict], stream: list[dict]) -> tuple[list[str], list[str], str]:
    """(problems, cascaded deletes, summary) of the stream against the trail."""
    problems: list[str] = []
    entities = list(dict.fromkeys(o["entity"] for o in trail))
    snapshot = [s for s in stream if s["tx"] == LOAD_TX]
    changes = [s for s in stream if s["tx"] != LOAD_TX]

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
            f"the stream delivered {len(got_groups)} source transactions, the trail has only {len(exp_groups)}"
        )
    split = max(0, len(exp_groups) - len(got_groups))
    before = [o for g in exp_groups[:split] for o in g]

    # The snapshot: the trail up to the split, replayed, is each table's state.
    want = replay(before)
    for entity in entities:
        inserted = next((o["row"] for o in trail if o["entity"] == entity and o["op"] == "insert"), {})
        got = sorted(
            tuple((c, norm(v)) for c, v in sorted(s["row"].items()) if c in inserted)
            for s in snapshot
            if s["entity"] == entity
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
            elif exp is not None and got["op"] != "delete" and (exp["op"], exp["entity"]) == (got["op"], got["entity"]):
                # The operation the trail expected, with the wrong values: said
                # once, and the pairing moves on rather than failing every one after.
                problems.append(f"{what}: {matches(exp, got)}")
                i += 1
            elif got["op"] == "delete":
                cascaded.append(f"{what}: delete on {got['entity']} {got['old']}")
            else:
                why = matches(exp, got) if exp is not None else "nothing more was expected"
                problems.append(f"{what}: unexpected {got['op']} on {got['entity']}: {why}")
        for exp in exp_ops[i:]:
            problems.append(f"{what}: {exp['op']} on {exp['entity']} never arrived")

    summary = (
        f"{len(trail)} operation(s) in the trail: {len(before)} in the snapshot, "
        f"{len(trail) - len(before)} as {len(got_groups)} source transaction(s) of changes "
        f"({len(cascaded)} cascaded delete(s) beside them), over {len(entities)} table(s)"
    )
    return problems, cascaded, summary


# ----------------------------------------------------------------- main ----


def main() -> int:
    if len(sys.argv) != 3:
        sys.exit(__doc__.strip().splitlines()[2])
    trail_file, coll = Path(sys.argv[1]), sys.argv[2]
    proj = os.environ["XP_PROJECT"]
    work = Path(os.environ["XP_WORK_DIR"]) / "cdc"
    work.mkdir(parents=True, exist_ok=True)

    trail = [o for o in read_jsonl(trail_file) if not o.get("dry_run")]
    entities = list(dict.fromkeys(o["entity"] for o in trail))

    # The stream's output: every changed version of every table, as operations.
    per_table = []
    for entity in entities:
        table = f"{entity}_changes"
        versions = get_table_versions(proj, coll, table)
        parquets = get_table_data(proj, coll, table, versions, work)
        rows = concat(convert_parquet_to_json(parquets), work / f"{table}.rows.jsonl")
        per_table.append(to_ops(rows, entity))
    stream = in_order(concat(per_table, work / "all.ops.jsonl"), work / "actual.jsonl")

    problems, cascaded, summary = compare(trail, read_jsonl(stream))

    (work / "report.txt").write_text(
        summary + "\n" + "".join(f"  {p}\n" for p in problems) + "".join(f"  cascaded: {c}\n" for c in cascaded),
        encoding="utf-8",
    )
    print(summary)
    for p in problems[:20]:
        print(f"  {p}")
    if len(problems) > 20:
        print(f"  ... {len(problems) - 20} more in {work / 'report.txt'}")
    return 1 if problems else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except TddError as exc:  # a tool that failed ends the check with what it said
        sys.exit(str(exc))
