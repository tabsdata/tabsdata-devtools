#
# Copyright 2026 Tabsdata Inc.
#

"""How a run's transactions are applied: serial, interleaved, nested or a mix.

``modify-data`` plans a list of transactions; a *schedule* says in what order
their statements run and when each one begins and commits. Every mode is a
pure function of the transactions' sizes, so a run is as repeatable as its
plan, and a dry run can say what a real one would do. ``concurrency`` is how
many transactions are open at once:

* ``serial`` -- one transaction at a time: begin, every statement, commit.
* ``interleaved`` -- up to ``concurrency`` transactions open at once, one
  statement from each in turn; a transaction commits right after its last
  statement and the next pending one begins in its place, so commits land
  between the others' statements and come in start order when the sets are
  alike.
* ``nested`` -- a nest of up to ``concurrency``: the outer transaction begins
  and runs one statement, the next begins inside it and does the same, down to
  the innermost, which runs the rest of its statements and commits; then each
  enclosing one runs the rest of its own and commits. Commits come in reverse
  start order and every transaction's life lies within the one begun before
  it. Then the next nest.
* ``mix`` -- the transactions in groups of ``concurrency``, each group the
  next of serial, interleaved, nested, round and round -- as ``--ops Mix``
  cycles the verbs over the sets -- so one run leaves every shape behind.

One thread drives a schedule, each open transaction on a connection of its
own: that is what makes the interleaving exact. It is also why two open
transactions must never want the same row -- the second would wait for a
commit that cannot come until it returns -- so :func:`contention` is checked
before a concurrent schedule runs, and, on a dialect that locks every row a
DELETE scans, :func:`scan_waits` over its tables without a key.
"""

from __future__ import annotations

import enum
from collections import deque
from dataclasses import dataclass, field

from tabsdata_dev.common.systems import constants
from tabsdata_dev.common.systems.datagen import OpKind, Transaction
from tabsdata_dev.common.systems.errors import TdxError


class TrxMode(str, enum.Enum):
    SERIAL = "serial"
    INTERLEAVED = "interleaved"
    NESTED = "nested"
    MIX = "mix"


MODES = tuple(m.value for m in TrxMode)
_MIX_CYCLE = (TrxMode.SERIAL, TrxMode.INTERLEAVED, TrxMode.NESTED)

# Transactions open at once unless --trx-concurrency says otherwise: enough
# for every shape to show, few enough for any server's connection limit.
DEFAULT_CONCURRENCY = 4


class Action(str, enum.Enum):
    BEGIN = "begin"
    STATEMENT = "statement"
    COMMIT = "commit"


@dataclass(frozen=True)
class Step:
    """One move of a schedule: ``txn`` begins, runs its ``index``-th statement,
    or commits."""

    txn: int
    action: Action
    index: int = -1


@dataclass
class Schedule:
    mode: TrxMode
    concurrency: int  # transactions open at once; 1 under serial
    steps: list[Step] = field(default_factory=list)
    # The groups the run was applied in, in order: the mode each ran under and
    # how many transactions it held -- one group for serial and interleaved,
    # one per nest, one per group of a mix.
    parts: list[tuple[TrxMode, int]] = field(default_factory=list)

    @property
    def transactions(self) -> int:
        return sum(1 for s in self.steps if s.action is Action.COMMIT)

    @property
    def commit_order(self) -> list[int]:
        """The transactions' numbers in the order they commit -- the order a
        change-data-capture consumer receives them."""
        return [s.txn for s in self.steps if s.action is Action.COMMIT]

    @property
    def label(self) -> str:
        """``serial``, or the mode with how many are open at once:
        ``nested(4)``."""
        if self.mode is TrxMode.SERIAL:
            return self.mode.value
        return f"{self.mode.value}({self.concurrency})"

    @property
    def summary(self) -> str:
        """The groups as applied: ``serial 4, interleaved 4, nested 2``."""
        return ", ".join(f"{mode.value} {count}" for mode, count in self.parts)


def parse_mode(raw: str) -> TrxMode:
    try:
        return TrxMode(str(raw).strip().lower())
    except ValueError:
        raise TdxError(
            f"{constants.OPT_TRX_MODE} must be {'|'.join(MODES)} (got: {raw})"
        ) from None


def parse_concurrency(raw: int | str) -> int:
    """A count of transactions open at once, at least 1."""
    try:
        n = int(str(raw).strip())
    except ValueError:
        raise TdxError(
            f"{constants.OPT_TRX_CONCURRENCY} must be a number >= 1 (got: {raw})"
        ) from None
    if n < 1:
        raise TdxError(f"{constants.OPT_TRX_CONCURRENCY} must be >= 1 (got: {n})")
    return n


def schedule(
    sizes: list[int], mode: TrxMode, concurrency: int = DEFAULT_CONCURRENCY
) -> Schedule:
    """The schedule for transactions of the given statement counts. The
    concurrency is capped at the number of transactions; serial ignores it."""
    txns = list(range(len(sizes)))
    if mode is TrxMode.SERIAL:
        parts = [(TrxMode.SERIAL, len(txns))] if txns else []
        return Schedule(mode, 1, _serial(txns, sizes), parts)
    width = max(1, min(concurrency, len(txns)))
    if mode is TrxMode.INTERLEAVED:
        parts = [(TrxMode.INTERLEAVED, len(txns))] if txns else []
        return Schedule(mode, width, _interleaved(txns, sizes, width), parts)
    steps: list[Step] = []
    parts = []
    for i, group in enumerate(_groups(txns, width)):
        part = TrxMode.NESTED if mode is TrxMode.NESTED else _MIX_CYCLE[i % 3]
        if part is TrxMode.SERIAL:
            steps.extend(_serial(group, sizes))
        elif part is TrxMode.INTERLEAVED:
            steps.extend(_interleaved(group, sizes, len(group)))
        else:
            steps.extend(_nested(group, sizes))
        parts.append((part, len(group)))
    return Schedule(mode, width, steps, parts)


def _groups(txns: list[int], size: int) -> list[list[int]]:
    return [txns[i : i + size] for i in range(0, len(txns), size)]


def _serial(txns: list[int], sizes: list[int]) -> list[Step]:
    steps: list[Step] = []
    for t in txns:
        steps.append(Step(t, Action.BEGIN))
        steps.extend(Step(t, Action.STATEMENT, i) for i in range(sizes[t]))
        steps.append(Step(t, Action.COMMIT))
    return steps


def _interleaved(txns: list[int], sizes: list[int], width: int) -> list[Step]:
    steps: list[Step] = []
    pending = deque(txns)
    open_: list[int] = []
    cursor = {t: 0 for t in txns}

    def begin_next() -> None:
        t = pending.popleft()
        steps.append(Step(t, Action.BEGIN))
        open_.append(t)

    while pending and len(open_) < width:
        begin_next()
    while open_:
        for t in list(open_):  # one statement each, in start order
            if cursor[t] < sizes[t]:
                steps.append(Step(t, Action.STATEMENT, cursor[t]))
                cursor[t] += 1
            if cursor[t] >= sizes[t]:
                steps.append(Step(t, Action.COMMIT))
                open_.remove(t)
                if pending:
                    begin_next()  # joins the next round
    return steps


def _nested(nest: list[int], sizes: list[int]) -> list[Step]:
    steps: list[Step] = []
    cursor = {t: 0 for t in nest}
    for t in nest:  # down: begin, one statement, the next inside
        steps.append(Step(t, Action.BEGIN))
        if sizes[t] > 0:
            steps.append(Step(t, Action.STATEMENT, 0))
            cursor[t] = 1
    for t in reversed(nest):  # up: the rest, then commit
        steps.extend(Step(t, Action.STATEMENT, i) for i in range(cursor[t], sizes[t]))
        steps.append(Step(t, Action.COMMIT))
    return steps


def contention(transactions: list[Transaction]) -> list[tuple[str, dict]]:
    """The rows two or more transactions of the run update or delete -- each
    as ``(table, key)`` -- which a concurrent schedule cannot apply: whichever
    transaction reaches such a row second waits for the first to commit, and
    one thread cannot get there. A plan never repeats a target unless it asks
    for more updates than a table has rows left, so this names that case."""
    seen: dict[tuple[str, tuple], set[int]] = {}
    for t, txn in enumerate(transactions):
        for ch in txn:
            if ch.kind is OpKind.INSERT or not ch.where:
                continue
            key = (ch.table, tuple(sorted((k, str(v)) for k, v in ch.where.items())))
            seen.setdefault(key, set()).add(t)
    return [(table, dict(key)) for (table, key), txns in seen.items() if len(txns) > 1]


def scan_waits(
    transactions: list[Transaction], sched: Schedule, scanned: set[str]
) -> tuple[int, str, int] | None:
    """The first statement of `sched` that would wait on its own run, on a
    dialect whose DELETE locks every row it scans (MySQL, Db2): a DELETE of a
    table in `scanned` -- one with no key and no unique index, so the
    statement reads all of it -- while another open transaction has already
    written that table and holds its rows until it commits, which the one
    thread cannot reach. An UPDATE does not wait there: both read the last
    committed version of a row another transaction holds and pass it by when
    it does not match (MySQL's semi-consistent read), and one that matches is
    the same row, which :func:`contention` refuses. Returns (txn, table, blocker)
    or None. The schedule's order decides it: a nest whose transactions all
    begin on another table never meets one (the innermost writes the scanned
    table with nothing else open on it), an interleaved run soon does."""
    if not scanned:
        return None
    written: dict[int, set[str]] = {}
    for step in sched.steps:
        if step.action is Action.BEGIN:
            written[step.txn] = set()
        elif step.action is Action.COMMIT:
            written.pop(step.txn, None)
        else:
            ch = transactions[step.txn][step.index]
            if ch.table in scanned and ch.kind is OpKind.DELETE:
                for other, tables in written.items():
                    if other != step.txn and ch.table in tables:
                        return step.txn, ch.table, other
            written[step.txn].add(ch.table)
    return None
