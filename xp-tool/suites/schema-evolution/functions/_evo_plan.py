#
# Copyright 2026 Tabsdata Inc.
#

"""_evo_plan — the schema-evolution policy every table destination is held to, as
cases: the frames written, in which order, and what each leaves in its table.

Standard library only: ``evo_frames.py`` builds its publishers' frames from it,
``gen_suites.py`` the subscribers and the suites, and ``scripts/verify_evo.py``
holds the database to it, so none of them can drift. The cases are tabsdata-os'
shared schema policy itests (``testi_tabsdatak.conn.common.sql.schema.policy``)
run end to end through a server:

- ``schema_evolution="strict"`` (every destination's default) refuses a batch with
  a column the table lacks or a wider type; ``"update"`` adds the column and
  widens the type.
- A column the batch lacks is written NULL either way, and a merge keeps the
  stored value in the rows it updates.
- A refused write leaves the table as it was, and says why: ``SQL_COMMON_10``.

Every case owns its table and is written in two PHASES, each phase a set of
publishers triggered one at a time (a non-detached ``tdk fn trigger``, which
waits for the subscribers): phase 1 makes every table -- a ``replace`` of the
seed frame, or a merge's first batch -- and phase 2 writes the frame under test.
A publisher feeds one subscriber per case (and per engine) that writes it, so the
cases of a phase run side by side on tables of their own. A write that is refused
has a publisher of its own and is triggered after the others: its transaction
fails, and nothing that should succeed shares it.

A non-detached ``tdk fn trigger`` exits non-zero when a run of its plan failed, so
a publisher whose writes may fail is triggered by ``verify_evo.py --trigger``,
which reads the subscribers' workers instead (``tdk worker list``): each must have
run to the end, and only one whose write may fail may have failed. After each
phase every table must hold exactly its state, read from the
database itself; and a refused write's subscriber must have failed with the
refusal, read from its worker's log -- a table left alone because its subscriber
never ran is not a refusal.
"""

from __future__ import annotations

from typing import NamedTuple

ID, NAME, SCORE, EXTRA, OP = "id", "name", "score", "extra", "op"
STRICT, UPDATE = "strict", "update"
APPEND, REPLACE, MERGE = "append", "replace", "merge"
BEYOND_INT32 = 2**40

#: What a refused write's worker log says (tabsdatak.conn.common.sql.error).
REFUSAL_CODE = "SQL_COMMON_10"
REFUSAL_TEXT = "does not allow the change"


class Frame(NamedTuple):
    """A publisher's frame: columns as (name, polars type name), rows in order."""

    columns: tuple[tuple[str, str], ...]
    rows: tuple[tuple, ...]


_BASE = ((ID, "Int64"), (NAME, "String"), (SCORE, "Int64"))
_ADDED = (*_BASE, (EXTRA, "String"))
_LACKING = ((ID, "Int64"), (NAME, "String"))
_NARROW = ((ID, "Int64"), (NAME, "String"), (SCORE, "Int32"))

#: publisher (and its output table) -> the frame it publishes.
FRAMES: dict[str, Frame] = {
    "evo_base": Frame(_BASE, ((1, "one", 10),)),
    "evo_narrow": Frame(_NARROW, ((1, "one", 10),)),
    "evo_merge_first": Frame((*_BASE, (OP, "String")), ((1, "one", 10, "i"),)),
    "evo_added": Frame(_ADDED, ((2, "two", 20, "x"),)),
    "evo_added_refused": Frame(_ADDED, ((2, "two", 20, "x"),)),
    "evo_lacking": Frame(_LACKING, ((2, "two"),)),
    "evo_wide": Frame(_BASE, ((2, "two", BEYOND_INT32),)),
    "evo_wide_strict": Frame(_BASE, ((2, "two", BEYOND_INT32),)),
    "evo_merge_lacking": Frame(
        (*_LACKING, (OP, "String")), ((1, "uno", "u"), (2, "two", "i"))
    ),
    "evo_merge_added": Frame((*_ADDED, (OP, "String")), ((2, "two", 20, "x", "i"),)),
    "evo_merge_added_refused": Frame(
        (*_ADDED, (OP, "String")), ((2, "two", 20, "x", "i"),)
    ),
}


class State(NamedTuple):
    """A table's columns (as a set: order and case are the database's) and its
    rows over those columns, in that order."""

    columns: tuple[str, ...]
    rows: tuple[tuple, ...]


class Write(NamedTuple):
    publisher: str
    mode: str
    evolution: str


class Case(NamedTuple):
    name: str
    #: What it proves, for the check's messages.
    what: str
    merge: bool
    seed: Write
    #: None: the case is its seed alone.
    write: Write | None
    #: The table after phase 1.
    seeded: State
    #: The table after phase 2; more than one when the database decides.
    final: tuple[State, ...]
    #: Whether the phase-2 write must be refused (with REFUSAL_CODE).
    refused: bool = False


_SEEDED = State((ID, NAME, SCORE), ((1, "one", 10),))
_WITH_EXTRA = State((ID, NAME, SCORE, EXTRA), ((1, "one", 10, None), (2, "two", 20, "x")))
_MISSING = State((ID, NAME, SCORE), ((1, "one", 10), (2, "two", None)))
_WIDENED = State((ID, NAME, SCORE), ((1, "one", 10), (2, "two", BEYOND_INT32)))

CASES: tuple[Case, ...] = (
    Case(
        "created_exact",
        "a created table has only the batch's columns",
        False,
        Write("evo_base", REPLACE, STRICT),
        None,
        _SEEDED,
        (_SEEDED,),
    ),
    Case(
        "strict_new_column",
        "strict refuses a new column",
        False,
        Write("evo_base", REPLACE, STRICT),
        Write("evo_added_refused", APPEND, STRICT),
        _SEEDED,
        (_SEEDED,),
        refused=True,
    ),
    Case(
        "update_new_column",
        "update adds a new column, NULL in the rows before it",
        False,
        Write("evo_base", REPLACE, STRICT),
        Write("evo_added", APPEND, UPDATE),
        _SEEDED,
        (_WITH_EXTRA,),
    ),
    Case(
        "strict_missing_column",
        "strict writes a column the batch lacks NULL",
        False,
        Write("evo_base", REPLACE, STRICT),
        Write("evo_lacking", APPEND, STRICT),
        _SEEDED,
        (_MISSING,),
    ),
    Case(
        "update_missing_column",
        "update writes a column the batch lacks NULL",
        False,
        Write("evo_base", REPLACE, STRICT),
        Write("evo_lacking", APPEND, UPDATE),
        _SEEDED,
        (_MISSING,),
    ),
    # A wider type of the same kind is the database's to take or refuse under
    # strict: a 32-bit column can hold 2**40 nowhere, but some databases have
    # one integer type only, so the batch is not wider there.
    Case(
        "strict_wider_type",
        "strict leaves a wider integer to the database, which refuses it or holds it",
        False,
        Write("evo_narrow", REPLACE, STRICT),
        Write("evo_wide_strict", APPEND, STRICT),
        _SEEDED,
        (_SEEDED, _WIDENED),
    ),
    Case(
        "update_wider_type",
        "update widens a 32-bit integer column to hold 2**40",
        False,
        Write("evo_narrow", REPLACE, STRICT),
        Write("evo_wide", APPEND, UPDATE),
        _SEEDED,
        (_WIDENED,),
    ),
    Case(
        "merge_strict_missing_column",
        "a strict merge keeps the stored value of a column the batch lacks",
        True,
        Write("evo_merge_first", MERGE, STRICT),
        Write("evo_merge_lacking", MERGE, STRICT),
        _SEEDED,
        (State((ID, NAME, SCORE), ((1, "uno", 10), (2, "two", None))),),
    ),
    Case(
        "merge_update_missing_column",
        "an update merge keeps the stored value of a column the batch lacks",
        True,
        Write("evo_merge_first", MERGE, UPDATE),
        Write("evo_merge_lacking", MERGE, UPDATE),
        _SEEDED,
        (State((ID, NAME, SCORE), ((1, "uno", 10), (2, "two", None))),),
    ),
    Case(
        "merge_strict_new_column",
        "a strict merge refuses a new column",
        True,
        Write("evo_merge_first", MERGE, STRICT),
        Write("evo_merge_added_refused", MERGE, STRICT),
        _SEEDED,
        (_SEEDED,),
        refused=True,
    ),
    Case(
        "merge_update_new_column",
        "an update merge adds a new column",
        True,
        Write("evo_merge_first", MERGE, UPDATE),
        Write("evo_merge_added", MERGE, UPDATE),
        _SEEDED,
        (_WITH_EXTRA,),
    ),
)

#: The merge key and marker every merge case writes with.
MERGE_KEY, MERGE_OP = ID, OP


class Destination(NamedTuple):
    #: Whether it takes ``if_table_exists="merge"`` (and runs the merge cases).
    merge: bool = False
    #: ``<system>.schema_evolution_engine`` values each append case runs under,
    #: one table each; ``(None,)`` when there is no choice (or one engine only).
    engines: tuple[str | None, ...] = (None,)
    #: Whether a write creates its table; one that cannot (StarRocks) has the
    #: check's setup create each seeded table first, with the seed's types.
    creates: bool = True
    #: Whether a write makes a 32-bit column 64-bit when it creates the table --
    #: the SQL databases do (PostgreSQL makes it bigint) -- so the setup creates
    #: the narrow tables with DDL and their seeds append into them, as the
    #: tabsdata-os widening itests do; otherwise "wider" would compare equals.
    narrow_ddl: bool = False


#: lane -> what the destination does. The lane name is the system's family name
#: in tabsdatak.conn (``mssql`` runs on an ``mssqlserver`` system).
DESTINATIONS: dict[str, Destination] = {
    "postgres": Destination(narrow_ddl=True),
    "mysql": Destination(narrow_ddl=True),
    "mssql": Destination(narrow_ddl=True),
    "oracle": Destination(narrow_ddl=True),
    "db2": Destination(narrow_ddl=True),
    "clickhouse": Destination(),
    "starrocks": Destination(creates=False),
    "databricks": Destination(merge=True),
    "snowflake": Destination(merge=True, engines=("native", "iceberg")),
    "bigquery": Destination(merge=True, engines=("native", "iceberg")),
}


def engines(d: Destination, c: Case) -> tuple[str | None, ...]:
    """The engines a case runs under: a merge refuses ``native``, so it runs
    under the default alone."""
    return (None,) if c.merge else d.engines


def tables(lane: str) -> list[tuple[Case, str | None, str]]:
    """Every (case, engine, table) of a lane."""
    d = DESTINATIONS[lane]
    return [(c, e, table(c, e)) for c in cases(d.merge) for e in engines(d, c)]


def case(name: str) -> Case:
    for c in CASES:
        if c.name == name:
            return c
    raise KeyError(name)


def cases(merge: bool) -> tuple[Case, ...]:
    """The cases a destination runs: every append case, and the merge cases when
    it merges."""
    return tuple(c for c in CASES if merge or not c.merge)


def table(c: Case, engine: str | None) -> str:
    """The case's table: ``evo_<case>``, ``_<engine>`` when the destination has
    a choice of engines (each engine its own table, side by side)."""
    return f"evo_{c.name}" + (f"_{engine}" if engine else "")


def subscriber(c: Case, phase: int, engine: str | None) -> str:
    """The subscriber writing the case's phase (1: seed, 2: write)."""
    return f"{table(c, engine)}_{'seed' if phase == 1 else 'write'}"


def may_fail(c: Case) -> bool:
    """Whether the case's phase-2 write may fail: it must, or the database
    decides."""
    return c.refused or len(c.final) > 1


def publishers(phase: int, merge: bool) -> list[str]:
    """The phase's publishers, in trigger order: the ones whose writes succeed,
    then the ones whose writes may fail -- a failed transaction is never ahead
    of one that has to succeed."""
    writes = [
        (c.seed if phase == 1 else c.write, phase == 2 and may_fail(c))
        for c in cases(merge)
    ]
    out: list[str] = []
    for failing in (False, True):
        for w, fails in writes:
            if w is not None and fails == failing and w.publisher not in out:
                out.append(w.publisher)
    return out


def made_by_setup(lane: str, c: Case) -> bool:
    """Whether the check's setup creates the case's table (with the seed frame's
    types) rather than its seed write."""
    d = DESTINATIONS[lane]
    if c.seed.mode != REPLACE:
        return False
    return not d.creates or (d.narrow_ddl and c.seed.publisher == "evo_narrow")


def seed(lane: str, c: Case) -> Write:
    """The case's phase-1 write on a lane: an append into a table the setup made
    and the write could otherwise create (a replace would drop it and create its
    own); StarRocks' replace only truncates, so it keeps its replace."""
    d = DESTINATIONS[lane]
    if made_by_setup(lane, c) and d.creates:
        return c.seed._replace(mode=APPEND)
    return c.seed
