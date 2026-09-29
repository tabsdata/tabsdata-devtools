#
# Copyright 2026 Tabsdata Inc.
#
"""Check a CDC stream's output against the operations the domain was given.

    verify_cdc_ops.py OPS_FILE COLLECTION --cascades logged|unlogged --noops logged|unlogged

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
source transaction (an xid, or a GTID ordered by its sequence) and ordered by
the position in it. The trail's transactions pair with those by what they hold:
the first the stream delivered is where the snapshot ends, and from there each
of the trail's operations must appear in its source transaction, in order --
operation, table, key and values. What else a transaction carries is the
database's to say, and the suite says it:

--cascades logged    the rows an ON DELETE CASCADE takes with a delete arrive
                     in its transaction, each one (postgres, db2); unlogged: none
                     does (mysql's binlog has no row event for them).
--noops logged       an update setting the values a row has arrives (postgres
                     logs every UPDATE); unlogged: it does not, and a
                     transaction of nothing else never arrives at all (mysql,
                     db2).

Column names are compared without case: db2 reports them upper-cased, as its
catalog folds unquoted names, and the trail has the model's.

An update or delete of a row that is not there -- a cascade took it -- arrives
under neither. Cascaded deletes are counted and listed, not refused. The transactions before the snapshot's end,
replayed with their cascades, must leave exactly the snapshot's rows in each
table. A transaction the trail has and the stream lost, or one the stream has
and the trail does not, is reported alone, and the pairing goes on after it.
Exit 0 when both hold, 1 with what differs otherwise.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

from tdd import TddError, tdd  # put on the path by `tdd _xp-execute`

LOAD_TX = "initial-load"
LOGGED, UNLOGGED = "logged", "unlogged"
# What applying an operation did to the tables.
CHANGED, SAME, ABSENT = "changed", "same", "absent"

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
# The snapshot first, then the changes by source transaction and position. A
# source transaction is a number (postgres' xid), a GTID, `<server uuid>:<n>`
# (mysql), ordered by its n -- every change comes from the one server -- or
# db2's 32 hex digits, which order as they read: fixed width, so as a string,
# and never through tonumber, which would round 32 digits and leave the ones
# with a-f in them strings, sorted after every number.
_IN_ORDER = r"""
  def txkey: if test("^[0-9a-fA-F]{32}$") then ascii_downcase
             elif test("^[0-9]+$") then tonumber
             elif test(":[0-9]+$") then (split(":") | last | tonumber)
             else . end;
  sort_by([.tx != "initial-load", (if .tx == "initial-load" then 0 else (.tx | txkey) end), .sq]) | .[]
"""


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


def fold(ops: list[dict]) -> list[dict]:
    """`ops` with every column name lower-cased, in the rows, keys and
    before-images. The trail names columns as the model does; a database that
    folds unquoted names reports them its way -- db2 upper-cases (EMP_NO), as
    its catalog stores them -- and the values are the same either way."""
    for o in ops:
        for part in ("row", "old", "key", "set"):
            if isinstance(o.get(part), dict):
                o[part] = {c.lower(): v for c, v in o[part].items()}
    return ops


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


class Tables:
    """Tables as the trail's operations leave them. A row is known by the
    columns updates and deletes name it by (``keys``, from the whole trail); a
    table only ever inserted into is known by the whole row. A delete cascades
    as the database does and the trail does not say: every other table's rows
    that carry the deleted key's columns with its values go too (a foreign key
    is named as the key it references) -- the snapshot of a stream started
    under changes has had those deletes."""

    def __init__(self, trail: list[dict]):
        self.keys: dict[str, list[str]] = {}
        for o in trail:
            if "key" in o:
                self.keys.setdefault(o["entity"], list(o["key"]))
        self.state: dict[str, dict] = {}
        # (entity, columns) -> their values -> the rows' keys: what a cascade
        # looks rows up by, built on first use and kept as rows come and go.
        self.index: dict[tuple, dict[tuple, set]] = {}

    def _values(self, row: dict, cols: tuple) -> tuple | None:
        return tuple(norm(row[c]) for c in cols) if all(c in row for c in cols) else None

    def _indexed(self, entity: str, pk: tuple, row: dict, add: bool) -> None:
        for (e, cols), idx in self.index.items():
            if e == entity and (v := self._values(row, cols)) is not None:
                (idx.setdefault(v, set()).add if add else idx.get(v, set()).discard)(pk)

    def apply(self, o: dict) -> str:
        """Apply `o`: CHANGED, SAME (an update to the values the row already
        has) or ABSENT (an update or delete of a row that is not there -- a
        cascade took it). A delete's cascade is left in ``took``, (entity,
        row) each."""
        self.took: list[tuple[str, dict]] = []
        t = self.state.setdefault(o["entity"], {})
        cols = self.keys.get(o["entity"])
        if o["op"] == "insert":
            pk = tuple(norm(o["row"][c]) for c in cols) if cols else tuple(sorted(o["row"].items()))
            if pk in t:
                self._indexed(o["entity"], pk, t[pk], add=False)
            t[pk] = dict(o["row"])
            self._indexed(o["entity"], pk, t[pk], add=True)
            return CHANGED
        pk = tuple(norm(o["key"][c]) for c in cols)
        if pk not in t:
            return ABSENT
        if o["op"] == "update":
            row = t[pk]
            changed = any(norm(row.get(c)) != norm(v) for c, v in o["set"].items())
            self._indexed(o["entity"], pk, row, add=False)
            row.update(o["set"])
            self._indexed(o["entity"], pk, row, add=True)
            return CHANGED if changed else SAME
        self._indexed(o["entity"], pk, t.pop(pk), add=False)
        cols = tuple(sorted(o["key"]))
        value = tuple(norm(o["key"][c]) for c in cols)
        for entity, rows in self.state.items():
            if entity == o["entity"]:
                continue
            if (entity, cols) not in self.index:
                idx: dict[tuple, set] = {}
                for rpk, r in rows.items():
                    if (v := self._values(r, cols)) is not None:
                        idx.setdefault(v, set()).add(rpk)
                self.index[(entity, cols)] = idx
            for rpk in list(self.index[(entity, cols)].get(value, ())):
                row = rows.pop(rpk)
                self._indexed(entity, rpk, row, add=False)
                self.took.append((entity, row))
        return CHANGED

    def rows(self) -> dict[str, list[tuple]]:
        """Each table's rows, as sorted normalized tuples."""
        return {
            e: sorted(tuple((c, norm(v)) for c, v in sorted(r.items())) for r in t.values())
            for e, t in self.state.items()
        }


def analyze(trail: list[dict]) -> tuple[dict[int, str], dict[int, list[tuple[str, dict]]]]:
    """Each operation's effect (by id: CHANGED, SAME or ABSENT) and each
    delete's cascade (by id), the whole trail replayed."""
    tables = Tables(trail)
    effect: dict[int, str] = {}
    took: dict[int, list[tuple[str, dict]]] = {}
    for o in trail:
        effect[id(o)] = tables.apply(o)
        if tables.took:
            took[id(o)] = tables.took
    return effect, took


def _row(row: dict, cols) -> tuple:
    return tuple((c, norm(row.get(c))) for c in sorted(cols))


def compare(
    trail: list[dict], stream: list[dict], cascades: str, noops: str
) -> tuple[list[str], list[str], str]:
    """(problems, cascaded deletes, summary) of the stream against the trail.
    ``cascades`` and ``noops`` say what the database logs (LOGGED or
    UNLOGGED): the rows a delete cascades to, and an update that sets the
    values a row has."""
    problems: list[str] = []
    entities = list(dict.fromkeys(o["entity"] for o in trail))
    snapshot = [s for s in stream if s["tx"] == LOAD_TX]
    changes = [s for s in stream if s["tx"] != LOAD_TX]
    effect, took = analyze(trail)
    # What the stream cannot carry: an operation on a row that is not there
    # (no database logs it) and, where they are not logged, the updates that
    # changed nothing -- a transaction of nothing else never arrives at all.
    idle = {i for i, e in effect.items() if e == ABSENT or (e == SAME and noops == UNLOGGED)}

    # The trail's transactions: one run of one verb numbers its own from 0.
    trail_txns: dict[tuple, list[dict]] = {}
    for o in trail:
        trail_txns.setdefault((o["ts"], o["domain"], o["verb"], o["txn"]), []).append(o)
    source_txns: dict[str, list[dict]] = {}
    for c in changes:
        source_txns.setdefault(c["tx"], []).append(c)
    exp_groups, got_groups = list(trail_txns.values()), list(source_txns.values())

    def opens(exp_ops: list[dict], got_ops: list[dict]) -> bool:
        """Whether `got_ops` is `exp_ops`' source transaction: its first
        operation is the first of theirs that changed something."""
        first = next((o for o in exp_ops if id(o) not in idle), exp_ops[0])
        return matches(first, got_ops[0]) is None

    # Where the snapshot ends: the trail transaction the stream's first change
    # transaction is. Counting from the end (the stream's N transactions are
    # the trail's last N) is only a first guess: a transaction that changed
    # nothing may be missing, one delivered twice may not.
    guess = max(0, len(exp_groups) - len(got_groups))
    split = guess
    if got_groups:
        near = sorted(range(max(0, guess - 200), min(len(exp_groups), guess + 200)), key=lambda s: abs(s - guess))
        split = next((s for s in near if opens(exp_groups[s], got_groups[0])), guess)
    else:
        split = len(exp_groups)
    before = [o for g in exp_groups[:split] for o in g]

    # The snapshot: the trail up to the split, replayed, is each table's state.
    tables = Tables(trail)
    for o in before:
        tables.apply(o)
    want = tables.rows()
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

    # The changes: transaction by transaction, paired by what they hold, the
    # trail's operations in order within each; anything more a cascaded delete.
    cascaded: list[str] = []

    def pair(exp_ops: list[dict], got_ops: list[dict]) -> None:
        o = exp_ops[0]
        what = f"{o['verb']}" + (f" seed {o['seed']}" if "seed" in o else "") + f" txn {o['txn']} (source tx {got_ops[0]['tx']})"
        pending = list(exp_ops)
        # The rows this transaction's deletes cascade to, as the stream would
        # carry them (a delete's before-image): each once.
        owed: dict[tuple, int] = {}
        for exp in exp_ops:
            for entity, row in took.get(id(exp), []):
                k = (entity, _row(row, row))
                owed[k] = owed.get(k, 0) + 1
        for got in got_ops:
            while pending and id(pending[0]) in idle and matches(pending[0], got) is not None:
                pending.pop(0)  # changed nothing, and was not logged
            exp = pending[0] if pending else None
            if exp is not None and matches(exp, got) is None:
                if effect[id(exp)] == SAME and noops == UNLOGGED:
                    problems.append(f"{what}: {exp['op']} on {exp['entity']} arrived, though it changed nothing")
                pending.pop(0)
            elif exp is not None and got["op"] != "delete" and (exp["op"], exp["entity"]) == (got["op"], got["entity"]):
                # The operation the trail expected, with the wrong values: said
                # once, and the pairing moves on rather than failing every one after.
                problems.append(f"{what}: {matches(exp, got)}")
                pending.pop(0)
            elif got["op"] == "delete" and cascades == LOGGED:
                k = next(
                    (k for k in owed if k[0] == got["entity"] and owed[k] and k[1] == _row(got["old"], dict(k[1]))),
                    None,
                )
                if k is None:
                    problems.append(f"{what}: unexpected delete on {got['entity']} {got['old']}: no delete here cascades to it")
                else:
                    owed[k] -= 1
                    cascaded.append(f"{what}: delete on {got['entity']} {got['old']}")
            elif got["op"] == "delete":
                problems.append(f"{what}: unexpected delete on {got['entity']} {got['old']}: cascades are not logged")
            else:
                why = matches(exp, got) if exp is not None else "nothing more was expected"
                problems.append(f"{what}: unexpected {got['op']} on {got['entity']}: {why}")
        for exp in pending:
            if id(exp) not in idle:
                problems.append(f"{what}: {exp['op']} on {exp['entity']} never arrived")
        if cascades == LOGGED:
            for (entity, row), n in owed.items():
                if n:
                    problems.append(f"{what}: cascaded delete on {entity} {dict(row)} never arrived")

    def txn(ops: list[dict]) -> str:
        o = ops[0]
        return f"{o['verb']}" + (f" seed {o['seed']}" if "seed" in o else "") + f" txn {o['txn']}"

    def described(ops: list[dict]) -> str:
        return ", ".join(f"{o['op']} {o['entity']} {o.get('key') or o.get('row')}" for o in ops[:3]) + (
            f" (+{len(ops) - 3} more)" if len(ops) > 3 else ""
        )

    i, j = split, 0
    while i < len(exp_groups) or j < len(got_groups):
        exp_ops = exp_groups[i] if i < len(exp_groups) else None
        got_ops = got_groups[j] if j < len(got_groups) else None
        if exp_ops is not None and got_ops is not None and opens(exp_ops, got_ops):
            pair(exp_ops, got_ops)
            i, j = i + 1, j + 1
        elif exp_ops is not None and all(id(o) in idle for o in exp_ops):
            i += 1  # changed nothing: there may be no source transaction to pair
        elif exp_ops is not None and (
            got_ops is None or any(opens(e, got_ops) for e in exp_groups[i + 1 : i + 20])
        ):
            problems.append(
                f"{txn(exp_ops)} never arrived: {described(exp_ops)}"
            )
            i += 1
        else:
            problems.append(f"source tx {got_ops[0]['tx']} is in no trail transaction: {described(got_ops)}")
            j += 1

    after = trail[len(before) :]
    same = sum(1 for o in after if effect[id(o)] == SAME)
    summary = (
        f"{len(trail)} operation(s) in the trail: {len(before)} in the snapshot, "
        f"{len(after)} as {len(got_groups)} source transaction(s) of changes "
        f"({len(cascaded)} cascaded delete(s) beside them, cascades {cascades}; "
        f"{same} update(s) that changed nothing, {noops}), over {len(entities)} table(s)"
    )
    return problems, cascaded, summary


# ----------------------------------------------------------------- main ----


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("ops_file", type=Path)
    parser.add_argument("collection")
    # No default: what the database logs is the suite's to say, and a check
    # that accepts either lets a stream drop what it should carry.
    parser.add_argument(
        "--cascades",
        required=True,
        choices=(LOGGED, UNLOGGED),
        help="the rows an ON DELETE CASCADE takes: logged (postgres) -- each must arrive "
        "in its delete's transaction -- or unlogged (mysql's binlog) -- none may",
    )
    parser.add_argument(
        "--noops",
        required=True,
        choices=(LOGGED, UNLOGGED),
        help="an update setting the values a row has: logged (postgres) -- it must arrive "
        "-- or unlogged (mysql) -- it must not, nor a transaction of nothing else",
    )
    args = parser.parse_args()
    trail_file, coll = args.ops_file, args.collection
    proj = os.environ["XP_PROJECT"]
    work = Path(os.environ["XP_WORK_DIR"]) / "cdc"
    work.mkdir(parents=True, exist_ok=True)

    trail = fold([o for o in read_jsonl(trail_file) if not o.get("dry_run")])
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

    problems, cascaded, summary = compare(trail, fold(read_jsonl(stream)), args.cascades, args.noops)

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
