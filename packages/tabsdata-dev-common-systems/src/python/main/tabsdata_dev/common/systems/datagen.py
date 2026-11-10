#
# Copyright 2026 Tabsdata Inc.
#

"""Generic deterministic data generation — initial data and post-seed deltas.

A *model* (``models/<name>/``) ships:

  * ``entities.json`` — the list of entity (table) names it generates.
  * ``datagenerator.py`` — a ``datagenerator() -> Model`` factory. The ``Model``
    knows how to build a deterministic **initial** dataset of a given size, and
    declares one ``Entity`` per table that supports **deltas** (which ops, how
    many rows per set, how to build/target/mutate a row). A model whose data its
    own system loads instead (salesforce, from a snowfakery recipe) ships none,
    so it resolves by name but never appears in :func:`list_models`.

This module owns the base size / multiplier, the deterministic delta *planner*
(entity-selection / ops / sets / seed, model-agnostic) and the SQL rendering.
Determinism: the plan is a pure function of ``(model, spec, seeded counts)``, so
the same call sequence with the same options reproduces the same data. A fixed
``--seed N`` reserves the insert-ordinal block ``[N*STRIDE, (N+1)*STRIDE)`` so
distinct seeds mint distinct inserts and each seed replays the same ones.
``--seed auto`` just uses the last persisted seed + 1 (same block rule), so the
seed sequence alone makes a run repeatable — no separate insert cursor is kept.
"""

from __future__ import annotations

import enum
import json
import os
import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib import import_module
from pathlib import Path
from typing import ClassVar

from tabsdata_dev.common.systems.emit import Column, Table, sql_literal, sql_quote_ident
from tabsdata_dev.common.systems.errors import TdxError

# create-data --size is an integer multiplier: 1 is the base, N scales the
# sizeable entities to N * BASE_SIZE rows (fixed reference entities don't grow).
BASE_SIZE = 100

# A fixed `--seed N` reserves the insert-ordinal block [N*STRIDE, (N+1)*STRIDE).
FIXED_SEED_INSERT_STRIDE = 1000

# Initial data is seeded from this fixed base so a given size is reproducible.
INITIAL_SEED = 42

# The entity every model carries for `sentinel-data` alone: a row a test writes
# to mark a point in time, which it then waits to see arrive downstream. No
# model generates it and no Entity declares it, so create-data leaves it empty
# and modify-data never picks it.
SENTINEL_ENTITY = "xp_sentinel"
SENTINEL_COLUMNS = [
    Column("sentinel_key", "varchar(255)", nullable=False),
    Column("sentinel_ts", "timestamp", nullable=False),
]

_B36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def base36(n: int, width: int = 0) -> str:
    """Non-negative int -> base-36 string (``0-9a-z``), left-zero-padded to
    `width`. Delta recipes use it to pack a large insert ordinal into a short,
    unique CHAR key."""
    if n < 0:
        raise ValueError("base36 needs a non-negative int")
    out = ""
    while True:
        n, r = divmod(n, 36)
        out = _B36[r] + out
        if n == 0:
            return out.rjust(width, "0") if width else out


class OpKind(str, enum.Enum):
    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"


class OpSelector(str, enum.Enum):
    """The ``--ops`` selector — which verbs a modify-data run may emit."""

    INSERT = "insert"
    UPDATE = "update"
    DELETE = "delete"
    MIX = "mix"  # cycle insert -> update -> delete


_MIX_CYCLE = (OpKind.INSERT, OpKind.UPDATE, OpKind.DELETE)


@dataclass
class Change:
    """One INSERT / UPDATE / DELETE against one table."""

    kind: OpKind
    table: str
    columns: list[Column]
    row: dict | None = None
    set_values: dict | None = None
    where: dict | None = None


Transaction = list[Change]


# ======================================================================
# Model contract — implemented per model in models/<name>/datagenerator.py
# ======================================================================


class Entity:
    """A model table that ``modify-data`` may mutate.

    ``new_row`` builds a deterministic brand-new row (non-colliding PK) for
    INSERT ``#i``; ``target`` returns the PK predicate of the ``i``-th seeded row
    (0-based) for UPDATE / DELETE; ``mutate`` returns the column->new-value
    changes for an UPDATE. ``supports`` narrows the verbs an entity can take;
    ``rows_per_set`` is how many rows a ``--entity ALL`` run applies to this
    entity per set.

    Two hooks a model with state of its own overrides (bronze): ``new_rows``,
    the rows one INSERT adds -- one, unless an insert is a batch, as a period
    of a period snapshot is -- and ``pick``, the ``(where, set)`` of one UPDATE
    or DELETE (``set`` ``None`` for a DELETE), or ``None`` when no row is left
    to take it.

    ``snapshot`` marks a table whose file holds the whole state: a file domain
    takes its UPDATEs and DELETEs too, and stages the state after the changes
    (:meth:`Model.restage`) instead of the inserted rows."""

    table: str
    columns: list[Column]
    supports: tuple[OpKind, ...] = (OpKind.INSERT, OpKind.UPDATE, OpKind.DELETE)
    rows_per_set: int = 1
    snapshot: bool = False

    def new_row(self, rng: random.Random, i: int) -> dict:
        raise NotImplementedError

    def new_rows(self, rng: random.Random, i: int) -> list[dict]:
        return [self.new_row(rng, i)]

    def target(self, i: int, existing: int) -> dict:
        raise NotImplementedError

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        raise NotImplementedError

    def pick(
        self, kind: OpKind, rng: random.Random, i: int, existing: int
    ) -> tuple[dict, dict | None] | None:
        # mutate before target: the order the planner always called them in,
        # so a model's rng is drawn as it was.
        set_values = self.mutate(rng, i, existing) if kind is OpKind.UPDATE else None
        return self.target(i, existing), set_values


# The verbs a system lets an entity take, of those it supports (a system's
# `change_verbs`); a system without one takes every verb.
VerbFilter = Callable[[Entity], tuple[OpKind, ...]]


def verbs_on(system: object, entity: Entity) -> tuple[OpKind, ...]:
    """The verbs `entity` takes on `system`: what the entity supports, narrowed
    by the system's ``change_verbs`` when it has one -- a file domain takes
    INSERT (and a snapshot's UPDATE and DELETE), a kafka topic INSERT. Read off
    the system's type: it is what the nature can do, and a dry run, which
    reaches no system, plans by it too."""
    narrow = getattr(type(system), "change_verbs", None)
    return entity.supports if narrow is None else narrow(system, entity)


def restages_snapshots(system: object) -> bool:
    """Whether `system` stages a snapshot entity's whole state (a file store),
    off its type, as :func:`verbs_on` reads."""
    return bool(getattr(type(system), "restages_snapshots", False))


class Model:
    """A model: the delta entities plus a deterministic initial-data builder.

    ``entities`` is ordered parents-first so a transaction (and its inserts) that
    spans tables satisfies foreign keys. ``build_initial`` returns every
    generated table (a superset of the delta entities) in FK-safe load order.

    A model whose changes depend on its earlier ones sets ``replays``: every
    applied modify-data run's spec is kept in the domain's descriptor
    (``DomainInfo.changes``), and :func:`plan` hands them to :meth:`prepare`
    first, which rebuilds the model's state from the seed and those runs --
    replaying their plans -- so the next run continues it. ``kafka_recipe``
    makes redpanda's modify-data produce the model's INSERTs rather than a
    fresh batch of its seed."""

    entities: ClassVar[list[Entity]] = []
    replays: ClassVar[bool] = False
    kafka_recipe: ClassVar[bool] = False

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        raise NotImplementedError

    def prepare(self, ctx: PlanContext) -> None:
        """Called by :func:`plan` before it plans (a replaying model's hook)."""

    def restage(self, tables: set[str]) -> dict[str, list[Table]]:
        """The files a file domain stages for the snapshot entities in `tables`
        that the last plan changed: ``{entity: [Table, ...]}``, one file each."""
        return {}


@dataclass
class ChangeSpec:
    """A parsed ``modify-data`` request. ``entities`` names the entities to touch;
    ``rows_per_entity`` is how many changes each gets per set; ``sets`` is the
    number of transactions. ``seed`` shifts UPDATE/DELETE targets; ``insert_base``
    is the starting INSERT ordinal (the seed's own block, ``seed * STRIDE``)."""

    entities: list[str]
    ops: OpSelector
    sets: int
    rows_per_entity: dict[str, int]
    seed: int = 0
    insert_base: int = 0

    def to_dict(self) -> dict:
        """What the descriptor keeps of an applied run, for a replay."""
        return {
            "entities": list(self.entities),
            "ops": self.ops.value,
            "sets": self.sets,
            "rows": dict(self.rows_per_entity),
            "seed": self.seed,
            "insert_base": self.insert_base,
        }

    @classmethod
    def from_dict(cls, d: dict) -> ChangeSpec:
        return cls(
            entities=list(d["entities"]),
            ops=OpSelector(d["ops"]),
            sets=int(d["sets"]),
            rows_per_entity={k: int(v) for k, v in d["rows"].items()},
            seed=int(d["seed"]),
            insert_base=int(d["insert_base"]),
        )


@dataclass
class PlanContext:
    """What :meth:`Model.prepare` gets: the create-data ``size``, the seeded
    counts the plan is bounded by, the specs of the runs applied since the
    load, in order, and the system's verb filter -- so a replay plans each one
    as it was planned."""

    size: int = 1
    counts: dict[str, int] = field(default_factory=dict)
    history: list[ChangeSpec] = field(default_factory=list)
    verbs: VerbFilter | None = None

    def replan(self, model: Model, spec: ChangeSpec) -> list[Transaction]:
        """Plan an earlier run again, as it was planned: no ``prepare``, and
        an entity the model no longer has is left out."""
        known = {e.table for e in model.entities}
        names = [n for n in spec.entities if n in known]
        if not names:
            return []
        spec = ChangeSpec(
            names,
            spec.ops,
            spec.sets,
            spec.rows_per_entity,
            spec.seed,
            spec.insert_base,
        )
        return _plan_sets(model, spec, self.counts, self.verbs)


def seeded_rows(seeded: dict[str, int]) -> dict[str, int]:
    """Per-entity row counts from a descriptor's ``seeded``: a SQL domain's are
    already by table; a file domain's are by staged file,
    ``<fmt>/<entity>_<stamp>.<fmt>``, one per format, so an entity's count is
    its largest per format (every format holds the same rows, but one a table
    cannot be written as)."""
    per: dict[tuple[str, str], int] = {}
    out: dict[str, int] = {}
    for key, rows in seeded.items():
        fmt, sep, rest = key.partition("/")
        if not sep:
            out[key] = rows
            continue
        name = rest.rsplit(".", 1)[0]
        # <entity>_<YYYYMMDD>T<hhmmss>_<mmm>: the stamp is the last two parts.
        parts = name.rsplit("_", 2)
        entity = parts[0] if len(parts) == 3 else name
        per[(fmt, entity)] = per.get((fmt, entity), 0) + rows
    for (_, entity), rows in per.items():
        out[entity] = max(out.get(entity, 0), rows)
    return out


# ======================================================================
# Planning — generic (entity-selection / ops / sets), model-agnostic
# ======================================================================


def resolve_entities(model: Model, names: list[str]) -> list[Entity]:
    """Map requested `names` to the model's Entity objects, in model
    (parents-first) order, de-duplicated. Fails on an unknown name."""
    if not names:
        raise TdxError("modify-data: --entity must name at least one entity")
    known = {e.table: e for e in model.entities}
    unknown = [n for n in names if n not in known]
    if unknown:
        raise TdxError(
            f"modify-data: unknown entit{'y' if len(unknown) == 1 else 'ies'} "
            f"{', '.join(unknown)} — this model changes: {', '.join(known)}"
        )
    wanted = set(names)
    return [e for e in model.entities if e.table in wanted]


def plan(
    model: Model,
    spec: ChangeSpec,
    counts: dict[str, int],
    *,
    size: int = 1,
    history: list[ChangeSpec] | None = None,
    verbs: VerbFilter | None = None,
) -> list[Transaction]:
    """Build ``spec.sets`` transactions, applying ``spec.rows_per_entity`` changes
    to each requested entity per transaction (parents-first). ``counts`` -- the
    SEEDED per-table row counts, the rows ``Entity.target`` addresses -- bounds
    UPDATE / DELETE targets (see ``_Planner._take`` for how they are walked).
    `verbs` narrows what each entity takes on the system the plan is for.
    Deterministic for a given ``spec.seed`` / ``spec.insert_base`` (and, for a
    replaying model, the `history` of earlier runs and the create-data
    `size`)."""
    if spec.sets < 1:
        raise TdxError("modify-data: --sets must be >= 1")
    model.prepare(PlanContext(size, dict(counts), list(history or []), verbs))
    txns = _plan_sets(model, spec, counts, verbs)
    if not txns:
        raise TdxError(
            "modify-data: nothing to do — the requested entities / ops produced no "
            "operations (a domain with no data has no rows to update/delete; use "
            "--ops Insert or create-data first, or name entities that support the "
            "chosen op)"
        )
    return txns


def _plan_sets(
    model: Model,
    spec: ChangeSpec,
    counts: dict[str, int],
    verbs: VerbFilter | None,
) -> list[Transaction]:
    entities = resolve_entities(model, spec.entities)
    rng = random.Random(spec.seed)
    planner = _Planner(spec, counts, rng, entities, verbs)
    txns: list[Transaction] = []
    for t in range(spec.sets):
        txn = planner.build(t)
        if txn:
            txns.append(txn)
    return txns


def op_counts(transactions: list[Transaction]) -> dict[str, dict[OpKind, int]]:
    """Per-table INSERT / UPDATE / DELETE counts a plan applies, in first-touched
    order. ``modify-data`` prints this so the user sees exactly what each table
    got. Every listed table maps all three ops (missing ones are 0)."""
    counts: dict[str, dict[OpKind, int]] = {}
    for txn in transactions:
        for ch in txn:
            per = counts.setdefault(
                ch.table, {OpKind.INSERT: 0, OpKind.UPDATE: 0, OpKind.DELETE: 0}
            )
            per[ch.kind] += 1
    return counts


def net_row_deltas(transactions: list[Transaction]) -> dict[str, int]:
    """Net per-table row-count change a plan applies: ``+1`` per INSERT, ``-1``
    per DELETE, ``0`` per UPDATE. ``modify-data`` adds this to the domain's
    recorded ``entities`` counts so ``info`` / ``status`` and the next run's
    UPDATE / DELETE bounds stay in step with the data."""
    deltas: dict[str, int] = {}
    for txn in transactions:
        for ch in txn:
            if ch.kind is OpKind.INSERT:
                deltas[ch.table] = deltas.get(ch.table, 0) + 1
            elif ch.kind is OpKind.DELETE:
                deltas[ch.table] = deltas.get(ch.table, 0) - 1
    return deltas


class _Planner:
    def __init__(
        self,
        spec: ChangeSpec,
        counts: dict[str, int],
        rng: random.Random,
        entities: list[Entity],
        verbs: VerbFilter | None = None,
    ) -> None:
        self.spec = spec
        self.counts = counts
        self.rng = rng
        self.entities = entities
        self._verbs = {
            e.table: e.supports if verbs is None else verbs(e) for e in entities
        }
        self._cursor: dict[tuple[str, OpKind], int] = {}
        self._inserts = 0
        self._mix = 0
        # How many UPDATEs / DELETEs one run plans per table: the stride that
        # gives each seed a block of targets of its own.
        self._per_run: dict[tuple[str, OpKind], int] = {}
        kinds = [
            _MIX_CYCLE[t % len(_MIX_CYCLE)]
            if spec.ops is OpSelector.MIX
            else OpKind(spec.ops.value)
            for t in range(spec.sets)
        ]
        for kind in kinds:
            for entity in entities:
                if kind in self._verbs[entity.table]:
                    key = (entity.table, kind)
                    self._per_run[key] = self._per_run.get(
                        key, 0
                    ) + spec.rows_per_entity.get(entity.table, 1)

    def _next_kind(self) -> OpKind:
        if self.spec.ops is OpSelector.MIX:
            k = _MIX_CYCLE[self._mix % len(_MIX_CYCLE)]
            self._mix += 1
            return k
        return OpKind(self.spec.ops.value)

    def _take(self, entity: Entity, kind: OpKind) -> list[Change]:
        if kind not in self._verbs[entity.table]:
            return []
        if kind is OpKind.INSERT:
            i = self.spec.insert_base + self._inserts
            self._inserts += 1
            return [
                Change(kind, entity.table, entity.columns, row=row)
                for row in entity.new_rows(self.rng, i)
            ]
        # The seeded rows `target` addresses. DELETEs walk in from the tail,
        # each seed taking a block of its own (seed * deletes-per-run on), so a
        # run of `--seed AUTO` passes deletes a distinct row every time and stops
        # -- plans none, reports none -- once the seeded rows are used up.
        # UPDATEs walk from the head over the rows those deletes have not
        # reached. Offsetting by the seed alone (the old walk) against the
        # CURRENT row count repeated one target forever: a Mix pass adds a row
        # and a seed, and the two cancelled.
        seeded = self.counts.get(entity.table, 0)
        if seeded <= 0:
            return []
        key = (entity.table, kind)
        local = self._cursor.get(key, 0)
        self._cursor[key] = local + 1
        deletes = self._per_run.get((entity.table, OpKind.DELETE), 0)
        if kind is OpKind.UPDATE:
            alive = seeded - (self.spec.seed + 1) * deletes
            if alive <= 0:
                return []
            per_run = self._per_run.get(key, 1)
            index = (self.spec.seed * per_run + local) % alive
        else:
            position = self.spec.seed * deletes + local
            if position >= seeded:
                return []
            index = seeded - 1 - position
        picked = entity.pick(kind, self.rng, index, seeded)
        if picked is None:
            return []
        where, set_values = picked
        return [
            Change(
                kind, entity.table, entity.columns, set_values=set_values, where=where
            )
        ]

    def build(self, t: int) -> Transaction:
        kind = self._next_kind()
        out: Transaction = []
        for entity in self.entities:
            for _ in range(self.spec.rows_per_entity.get(entity.table, 1)):
                out.extend(self._take(entity, kind))
        return out


# ======================================================================
# Rendering — SQL
# ======================================================================


def render_sql(
    change: Change, quote: str = '"', reserved: frozenset[str] = frozenset()
) -> str:
    """Render one change to a portable SQL statement (no trailing ``;``)."""
    cols = {c.name: c for c in change.columns}
    if change.kind is OpKind.INSERT:
        assert change.row is not None
        used = [c for c in change.columns if not c.auto and c.name in change.row]
        names = ",".join(sql_quote_ident(c.name, quote, reserved) for c in used)
        vals = ",".join(sql_literal(change.row.get(c.name), c.sql_type) for c in used)
        return f"INSERT INTO {change.table} ({names}) VALUES ({vals})"
    if change.kind is OpKind.UPDATE:
        assert change.set_values is not None and change.where is not None
        sets = ", ".join(
            f"{sql_quote_ident(k, quote, reserved)} = {sql_literal(v, cols[k].sql_type)}"
            for k, v in change.set_values.items()
        )
        where = _where_sql(change.where, cols, quote, reserved)
        return f"UPDATE {change.table} SET {sets} WHERE {where}"
    assert change.where is not None
    return f"DELETE FROM {change.table} WHERE {_where_sql(change.where, cols, quote, reserved)}"


def _where_sql(
    where: dict, cols: dict[str, Column], quote: str, reserved: frozenset[str]
) -> str:
    return " AND ".join(
        f"{sql_quote_ident(k, quote, reserved)} = {sql_literal(v, cols[k].sql_type)}"
        for k, v in where.items()
    )


# ======================================================================
# Rendering — operation lines (--emit-ops)
# ======================================================================


def op_line(run: dict, txn: int, change: Change, commit: int | None = None) -> dict:
    """One change as a CDC-style record: the run's fields (``run``), the
    transaction's number within the run, its rank in the run's commit order
    when the run has one (``commit``, modify-data), ``op`` and ``entity``, then
    ``row`` for an INSERT, ``key`` + ``set`` for an UPDATE, ``key`` for a
    DELETE. An INSERT carries every value the model generated, ``auto`` columns
    included, as a file load does: the surrogate keys are what later changes
    and other entities refer to."""
    out: dict = {**run, "txn": txn}
    if commit is not None:
        out["commit"] = commit
    out.update(op=change.kind.value, entity=change.table)
    if change.kind is OpKind.INSERT:
        assert change.row is not None
        out["row"] = {
            c.name: change.row[c.name] for c in change.columns if c.name in change.row
        }
    else:
        out["key"] = change.where
        if change.kind is OpKind.UPDATE:
            out["set"] = change.set_values
    return out


def tables_of(transactions: list[Transaction]) -> list[Table]:
    """The INSERTs of a plan as tables, one per entity in first-touched order:
    what a file is staged from, or a topic's messages produced from."""
    by_table: dict[str, tuple[list[Column], list[dict]]] = {}
    for txn in transactions:
        for ch in txn:
            if ch.kind is OpKind.INSERT:
                assert ch.row is not None
                by_table.setdefault(ch.table, (ch.columns, []))[1].append(ch.row)
    return [Table(name, cols, rows) for name, (cols, rows) in by_table.items()]


def size_of(data: str | None) -> int:
    """The create-data ``--size`` a domain recorded (1 when it is not a
    number, as on a descriptor from before it was)."""
    try:
        return max(1, int(data or 1))
    except ValueError:
        return 1


def initial_changes(tables: list[Table]) -> Transaction:
    """A create-data load as one transaction of INSERTs, in load order."""
    return [
        Change(OpKind.INSERT, t.name, t.columns, row=row)
        for t in tables
        for row in t.rows
    ]


def _json_value(v):
    # Dates and times as ISO strings; Decimal (and anything else a model mints)
    # as its string, so a value keeps its precision rather than becoming a float.
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return str(v)


def append_ops(
    path: str | Path,
    domain: str,
    verb: str,
    transactions: list[Transaction],
    *,
    dry_run: bool,
    seed: int | None = None,
    trx_mode: str | None = None,
    commit_order: list[int] | None = None,
) -> int:
    """Append `transactions` to `path` as JSON lines, one per change. Every
    line names its run -- ``run``, an id of its own (two runs of one verb on one
    domain can fall in the same second, and their transaction numbers would
    then be one run's), ``ts`` (UTC, to the second), ``domain``, ``verb``,
    ``seed`` and ``trx_mode`` when the verb has them, ``dry_run`` -- and
    numbers its transaction from 0 within that run, so one file can hold the
    trail of many runs and domains. With a `commit_order` (modify-data) the
    transactions are written in that order, the order a change-data-capture
    consumer receives them, each line carrying its transaction's rank in it as
    ``commit``; ``txn`` stays the plan's number, so under a nested run it
    counts down. A run's lines go out in one append, so runs sharing the file
    (a batch's children, a live script's entries) never interleave inside one.
    Returns the number of lines."""
    stamp = datetime.now(UTC).replace(tzinfo=None, microsecond=0)
    run: dict = {
        "run": uuid.uuid4().hex[:12],
        "ts": stamp.isoformat(),
        "domain": domain,
        "verb": verb,
    }
    if seed is not None:
        run["seed"] = seed
    if trx_mode is not None:
        run["trx_mode"] = trx_mode
    run["dry_run"] = dry_run
    if commit_order is None:
        order = [(None, txn) for txn in range(len(transactions))]
    else:
        order = list(enumerate(commit_order))
    text = "".join(
        json.dumps(op_line(run, txn, ch, commit), default=_json_value) + "\n"
        for commit, txn in order
        for ch in transactions[txn]
    )
    if not text:
        return 0
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    data = text.encode("utf-8")
    fd = os.open(dest, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        view = memoryview(data)
        while view:
            view = view[os.write(fd, view) :]
    finally:
        os.close(fd)
    return text.count("\n")


# ======================================================================
# Model discovery / loading
# ======================================================================


def _models_root() -> Path:
    return Path(__file__).parent / "models"


def list_models() -> list[str]:
    """All models on disk (dir with both ``datagenerator.py`` and
    ``entities.json``)."""
    root = _models_root()
    if not root.is_dir():
        return []
    out = []
    for child in sorted(root.iterdir()):
        if (child / "datagenerator.py").is_file() and (
            child / "entities.json"
        ).is_file():
            out.append(child.name)
    return out


def model_dir(name: str) -> Path:
    """The model's directory, identified by its ``entities.json``. A model whose
    data a system loads by itself (salesforce) ships no ``datagenerator.py``, so
    it resolves here and is absent from :func:`list_models`."""
    d = _models_root() / name
    if not (d / "entities.json").is_file():
        raise TdxError(f"unknown model: {name} (known: {', '.join(list_models())})")
    return d


@dataclass
class EntityInfo:
    """One ``entities.json`` entry: the table `name` and whether it is
    `sizeable` — i.e. its row count grows with the ``--size`` multiplier
    (fixed reference entities, e.g. countries, are not sizeable)."""

    name: str
    sizeable: bool = True


def entity_specs(name: str) -> list[EntityInfo]:
    """The entities a model generates, in FK-safe order, with their sizeable
    markers, from ``entities.json`` (a list of ``{"name", "sizeable"}`` objects;
    a bare string is treated as sizeable for backward compatibility)."""
    path = model_dir(name) / "entities.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise TdxError(f"{path}: entities.json must be a list")
    out: list[EntityInfo] = []
    for e in data:
        if isinstance(e, str):
            out.append(EntityInfo(e, True))
        elif isinstance(e, dict) and isinstance(e.get("name"), str):
            out.append(EntityInfo(e["name"], bool(e.get("sizeable", True))))
        else:
            raise TdxError(f"{path}: each entity must be a name or {{name, sizeable}}")
    return out


def entities_of(name: str) -> list[str]:
    """The entity (table) names a model generates, from ``entities.json``."""
    return [e.name for e in entity_specs(name)]


def sizeable_entities(name: str) -> list[str]:
    """The names of the entities that grow with the ``--size`` multiplier."""
    return [e.name for e in entity_specs(name) if e.sizeable]


# The wire formats a kafka domain's messages take, per entity (``model.json``'s
# ``message_formats``); an entity it does not name is JSON.
MESSAGE_JSON, MESSAGE_AVRO, MESSAGE_PROTOBUF = "json", "avro", "protobuf"
MESSAGE_FORMATS = (MESSAGE_JSON, MESSAGE_AVRO, MESSAGE_PROTOBUF)


def message_formats(name: str) -> dict[str, str]:
    """``{entity: avro|protobuf}`` from the model's ``model.json``
    (``{"message_formats": {...}}``): the entities whose kafka messages are not
    JSON. ``{}`` for a model without one, as for every model that predates it."""
    path = model_dir(name) / "model.json"
    if not path.is_file():
        return {}
    raw = json.loads(path.read_text(encoding="utf-8")).get("message_formats") or {}
    known = set(entities_of(name))
    out: dict[str, str] = {}
    for entity, fmt in raw.items():
        if entity not in known:
            raise TdxError(f"{path}: message_formats names no entity: {entity}")
        if fmt not in MESSAGE_FORMATS:
            raise TdxError(
                f"{path}: {entity}: message format {fmt!r} is not one of "
                f"{', '.join(MESSAGE_FORMATS)}"
            )
        if fmt != MESSAGE_JSON:
            out[entity] = fmt
    return out


def load_model(name: str) -> Model:
    """Import ``models/<name>/datagenerator.py`` and return its ``Model``."""
    if not (model_dir(name) / "datagenerator.py").is_file():
        raise TdxError(
            f"model '{name}' has no datagenerator.py — its data is loaded by the "
            f"system that owns it, not by the shared pipeline"
        )
    module = import_module(f"{__package__}.models.{name}.datagenerator")
    if not hasattr(module, "datagenerator"):
        raise TdxError(f"model '{name}': datagenerator.py has no datagenerator() entry")
    model = module.datagenerator()
    if not isinstance(model, Model):
        raise TdxError(f"model '{name}': datagenerator() must return a Model")
    return model


def supported_ops(model: Model) -> set[OpKind]:
    ops: set[OpKind] = set()
    for e in model.entities:
        ops.update(e.supports)
    return ops


_OP_LETTER = {OpKind.INSERT: "I", OpKind.UPDATE: "U", OpKind.DELETE: "D"}
_OP_ORDER = (OpKind.INSERT, OpKind.UPDATE, OpKind.DELETE)


def ops_tag(supports: tuple[OpKind, ...]) -> str:
    """Compact ``I/U/D`` label for an entity's supported ``modify-data`` ops, in a
    stable insert/update/delete order."""
    return "/".join(_OP_LETTER[k] for k in _OP_ORDER if k in supports)


def op_applies(supports: tuple[OpKind, ...], ops: OpSelector) -> bool:
    """Whether an entity with `supports` takes at least one change under the `ops`
    selector — ``MIX`` acts if it supports any op; a single op must be supported."""
    if ops is OpSelector.MIX:
        return len(supports) > 0
    return OpKind(ops.value) in supports


def iud(
    insert: int = 0, update: int = 0, delete: int = 0, rows: int | None = None
) -> dict[str, int]:
    """The canonical per-entity counts object of a data verb's report:
    ``{"insert": .., "update": .., "delete": ..}``, plus ``rows`` -- the
    entity's count once the run is applied -- when the run was applied."""
    out = {"insert": insert, "update": update, "delete": delete}
    if rows is not None:
        out["rows"] = rows
    return out


def iud_lines(entities: dict[str, dict]) -> list[str]:
    """The view of a report's ``entities`` (``{name: iud(...)}``): one aligned
    line per entity, ``I=`` / ``U=`` / ``D=`` and ``(rows=N)`` when known --
    create-data and modify-data print the same lines from the same shape."""
    if not entities:
        return []
    width = max(len(name) for name in entities)
    lines = []
    for name, per in entities.items():
        rows = f"  (rows={per['rows']})" if "rows" in per else ""
        lines.append(
            f"  {name:<{width}}  I={per['insert']}  U={per['update']}  "
            f"D={per['delete']}{rows}"
        )
    return lines
