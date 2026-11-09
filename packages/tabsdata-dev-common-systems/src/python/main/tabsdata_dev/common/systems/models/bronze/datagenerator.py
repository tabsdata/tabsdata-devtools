#
# Copyright 2026 Tabsdata Inc.
#

"""Data generator for the ``bronze`` model.

A medallion-bronze arrival-pattern simulator. Seven tables, one per pattern a
source system uses to deliver data to a bronze layer:

  full_snapshot      — entire current state, every batch
  insup_soft_delete  — rows changed since last extract, with ``deleted`` flag
                           (insert + update + soft-delete)
  insup_no_delete    — rows changed since last extract, deletes invisible
                           (insert + update only)
  cdc_stream         — I/U/D operations following the ``@td.cdc.*`` contract
  append_events      — immutable events, unique key per row
  period_snapshot    — the whole state at each month-end, ``period_end``
  log_lines          — an application log, one ``line`` per row (``log_line``)

Every table carries a monotonic ``sim_counter`` BIGINT (the only enforced PK).
The payload tables share a 10-column payload whose first two columns —
``tenant_id`` + ``entity_id`` — form a composite "business" key that is NOT
enforced by the schema. ``cdc_stream`` conforms to the ``@td.cdc.*`` CDC
contract: an ``op`` / ``tx`` / ``sq`` metadata triple plus an ``old`` + ``new``
pair per source column, so its identifiers carry ``@`` and ``.`` and must be
quoted.

The initial size is the batch count (``n`` = 100 x ``--size``); a batch is 100
rows, so each of the first five tables and the log emit ``n * 100`` rows; the
period snapshot holds ``n`` keys at each of three month-ends. The first five
are drawn from one ``random.seed(_BASE_SEED)`` sequence, exactly as before the
other two were added, which draw from generators of their own.

**Changes replay** (``Model.replays``). What a change may do depends on what
earlier changes did -- a CDC ``u`` needs a live key, a version needs a key that
exists, a snapshot file is the state after every change -- so ``prepare``
rebuilds each table's state from the seed and from every run applied since the
load (their specs, in the descriptor), planning each again, and the next run
continues it. In every run:

* an inserted row's ``sim_counter`` is ``_INSERT_BASE`` (past any seed) plus the
  rows inserted into its table before it, so it never repeats, whatever seeds
  the runs were given;
* every inserted or updated ``data_ts`` is a second past the table's last one
  (the log's ``ts`` one to four), from ``_NOW`` on -- after every seeded value
  -- so a ``data_ts`` cursor sees each change; a period's rows are all read
  then, the unchanged ones too, and a CDC delete carries the key's last state
  as the seed's do;
* a new version names a key that exists, an UPDATE or DELETE a row that is
  there (the planner's seeded index, moved to the nearest row still there),
  and a new key continues its tenant's sequence.
"""

from __future__ import annotations

import calendar
import random
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta

from tabsdata_dev.common.systems.datagen import (
    BASE_SIZE,
    INITIAL_SEED,
    Entity,
    Model,
    OpKind,
    PlanContext,
)
from tabsdata_dev.common.systems.emit import Column, Table
from tabsdata_dev.common.systems.models.logs.datagenerator import app_row

_BASE_SEED = 42
_NOW = datetime(2025, 1, 1, 0, 0, 0)
_SPAN = timedelta(days=365)
# An inserted row's sim_counter is this plus its table's insert count: past
# every seeded one (n * 100 rows, n = 100 x --size, below 1000).
_INSERT_BASE = 10_000_000
_BATCH_SIZE = 100

FULL = "brz_full_snapshot"
SOFT = "brz_insup_soft_delete"
NO_DELETE = "brz_insup_no_delete"
CDC = "brz_cdc_stream"
APPEND = "brz_append_events"
PERIOD = "brz_period_snapshot"
LOG = "brz_log_lines"
TABLES = (FULL, SOFT, NO_DELETE, CDC, APPEND, PERIOD, LOG)

# The period snapshot's seed: three month-ends, the last 2024-12-31 (period 2).
_FIRST_MONTH = 2024 * 12 + 9  # October 2024, as a month count
_SEED_PERIODS = 3
# The log's seed starts here, its lines at most 4 s apart: up to --size 100
# (a million lines) it ends before _NOW.
_LOG_START = datetime(2024, 6, 1)

TENANTS = ["T01", "T02", "T03"]
NAMES = [
    "alpha",
    "beta",
    "gamma",
    "delta",
    "epsilon",
    "zeta",
    "eta",
    "theta",
    "iota",
    "kappa",
    "lambda",
    "mu",
    "nu",
    "xi",
    "omicron",
    "pi",
    "rho",
    "sigma",
    "tau",
    "upsilon",
    "phi",
    "chi",
    "psi",
    "omega",
]
STATUSES = ["active", "pending", "review", "archived", "draft"]
CATEGORIES = ["A", "B", "C", "D", "E"]


def _fmt_dt(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _rand_ts(now: datetime, span: timedelta) -> datetime:
    return now - timedelta(seconds=random.randint(0, int(span.total_seconds())))


def _payload(tenant_id: str, entity_id: int, now: datetime, span: timedelta) -> dict:
    """A source-row payload — the 10 'data' columns each arrival pattern emits,
    and the same shape that CDC tracks old/new for. is_active defaults to 1;
    soft-delete swaps it for ``deleted``."""
    return {
        "tenant_id": tenant_id,
        "entity_id": entity_id,
        "data_ts": _fmt_dt(_rand_ts(now, span)),
        "name": random.choice(NAMES),
        "status": random.choice(STATUSES),
        "category": random.choice(CATEGORIES),
        "amount": round(random.uniform(0, 10000), 2),
        "quantity": random.randint(0, 1000),
        "score": round(random.uniform(0, 1), 6),
        "is_active": 1,
    }


class _KeyMint:
    """Mints (tenant_id, entity_id) tuples where entity_id is unique only within
    its tenant — so the composite key is what disambiguates rows. Tracks a
    per-tenant high-water mark."""

    def __init__(self, tenants: list[str]):
        self._next: dict[str, int] = {t: 1 for t in tenants}
        self._tenants = list(tenants)

    def new(self) -> tuple[str, int]:
        t = random.choice(self._tenants)
        eid = self._next[t]
        self._next[t] += 1
        return (t, eid)


def _gen_full_snapshot(batches, batch_size, now, span):
    mint = _KeyMint(TENANTS)
    pool = [mint.new() for _ in range(batch_size)]
    rows, counter = [], 0
    churn = max(1, batch_size // 5) if batch_size > 1 else 0
    for b in range(batches):
        if b > 0 and churn:
            for i in random.sample(range(batch_size), min(churn, batch_size)):
                pool[i] = mint.new()
        for tid, eid in pool:
            counter += 1
            r = _payload(tid, eid, now, span)
            r["sim_counter"] = counter
            rows.append(r)
    return rows


def _gen_insup_soft_delete(batches, batch_size, now, span):
    mint = _KeyMint(TENANTS)
    pool: list[tuple[str, int]] = []
    rows, counter = [], 0
    for _ in range(batches):
        for _ in range(batch_size):
            counter += 1
            roll = random.random()
            if not pool or roll < 0.4:
                key = mint.new()
                pool.append(key)
                deleted = 0
            elif roll < 0.8:
                key = random.choice(pool)
                deleted = 0
            else:
                key = pool.pop(random.randrange(len(pool)))
                deleted = 1
            r = _payload(key[0], key[1], now, span)
            r.pop("is_active")
            r["deleted"] = deleted
            r["sim_counter"] = counter
            rows.append(r)
    return rows


def _gen_insup_no_delete(batches, batch_size, now, span):
    mint = _KeyMint(TENANTS)
    pool: list[tuple[str, int]] = []
    rows, counter = [], 0
    for _ in range(batches):
        for _ in range(batch_size):
            counter += 1
            if not pool or random.random() < 0.5:
                key = mint.new()
                pool.append(key)
            else:
                key = random.choice(pool)
            r = _payload(key[0], key[1], now, span)
            r["sim_counter"] = counter
            rows.append(r)
    return rows


def _gen_append_events(batches, batch_size, now, span):
    """Each row gets a fresh composite key — entity_id is the per-tenant event
    sequence number."""
    mint = _KeyMint(TENANTS)
    rows, counter = [], 0
    for _ in range(batches):
        for _ in range(batch_size):
            counter += 1
            tid, eid = mint.new()
            r = _payload(tid, eid, now, span)
            r["sim_counter"] = counter
            rows.append(r)
    return rows


SOURCE_COLS: list[tuple[str, str]] = [
    ("tenant_id", "varchar(20)"),
    ("entity_id", "bigint"),
    ("data_ts", "datetime"),
    ("name", "varchar(80)"),
    ("status", "varchar(20)"),
    ("category", "varchar(20)"),
    ("amount", "decimal(12,2)"),
    ("quantity", "int"),
    ("score", "double"),
    ("is_active", "smallint"),
]


def _new_tx_id(rng=random) -> str:
    return str(uuid.UUID(int=rng.getrandbits(128), version=4))


def _gen_cdc_stream(batches, batch_size, now, span):
    """Emit I/U/D rows following the @td.cdc.* contract.

    Consecutive rows occasionally share a tx id (runs of 1-3) so the consumer
    sees changes grouped into transactions. Per-key state is kept so updates
    emit a real before-image. Per spec, deletes emit the row-state in ``new``
    and NULL in ``old``."""
    mint = _KeyMint(TENANTS)
    live: dict[tuple[str, int], dict] = {}
    rows, counter = [], 0
    tx_id, tx_seq, tx_left = None, 0, 0
    for _ in range(batches):
        for _ in range(batch_size):
            counter += 1
            if tx_left == 0:
                tx_id, tx_seq, tx_left = _new_tx_id(), 1, random.randint(1, 3)
            else:
                tx_seq += 1
            tx_left -= 1

            roll = random.random()
            if not live or roll < 0.4:
                op = "i"
                key = mint.new()
                new_state = _payload(key[0], key[1], now, span)
                live[key] = new_state
                old_state = None
            elif roll < 0.8:
                op = "u"
                key = random.choice(list(live.keys()))
                old_state = live[key]
                new_state = _payload(key[0], key[1], now, span)
                live[key] = new_state
            else:
                op = "d"
                key = random.choice(list(live.keys()))
                new_state = live.pop(key)
                old_state = None

            r: dict = {
                "sim_counter": counter,
                "@td.cdc.meta.op": op,
                "@td.cdc.meta.tx": tx_id,
                "@td.cdc.meta.sq": tx_seq,
            }
            for src_col, _ in SOURCE_COLS:
                r[f"@td.cdc.data.col.old.{src_col}"] = (
                    old_state[src_col] if old_state else None
                )
                r[f"@td.cdc.data.col.new.{src_col}"] = (
                    new_state[src_col] if new_state else None
                )
            rows.append(r)
    return rows


def _data_cols(flag_name: str) -> list[Column]:
    """10 payload columns for the non-CDC tables. The first two — tenant_id +
    entity_id — form a composite business key, intentionally NOT enforced. The
    soft-delete table swaps ``is_active`` for ``deleted``."""
    return [
        Column("tenant_id", "varchar(20)", nullable=False),
        Column("entity_id", "bigint", nullable=False),
        Column("data_ts", "datetime", nullable=False),
        Column("name", "varchar(80)"),
        Column("status", "varchar(20)"),
        Column("category", "varchar(20)"),
        Column("amount", "decimal(12,2)"),
        Column("quantity", "int"),
        Column("score", "double"),
        Column(flag_name, "smallint", nullable=False),
    ]


def _cdc_cols() -> list[Column]:
    cols: list[Column] = [
        Column("sim_counter", "bigint", nullable=False),
        Column("@td.cdc.meta.op", "char(1)", nullable=False),
        Column("@td.cdc.meta.tx", "varchar(36)", nullable=False),
        Column("@td.cdc.meta.sq", "int", nullable=False),
    ]
    for src_col, src_type in SOURCE_COLS:
        cols.append(Column(f"@td.cdc.data.col.old.{src_col}", src_type))
        cols.append(Column(f"@td.cdc.data.col.new.{src_col}", src_type))
    return cols


SIM_COUNTER = Column("sim_counter", "bigint", nullable=False)

_PAYLOAD_FIELDS = ("name", "status", "category", "amount", "quantity", "score")

_LOG_COLUMNS = [
    SIM_COUNTER,
    Column("ts", "timestamp"),
    Column("level", "varchar(5)"),
    Column("service", "varchar(16)"),
    Column("request_id", "char(12)"),
    Column("latency_ms", "int"),
    Column("message", "varchar(200)"),
    Column("line", "varchar(400)", nullable=False, log_line=True),
]


def _columns(table: str) -> list[Column]:
    if table == CDC:
        return _cdc_cols()
    if table == LOG:
        return list(_LOG_COLUMNS)
    cols = [SIM_COUNTER, *_data_cols("deleted" if table == SOFT else "is_active")]
    if table == PERIOD:
        cols.append(Column("period_end", "date", nullable=False))
    return cols


# ---- generated with a generator of their own: period snapshot, log ---------

Key = tuple[str, int]


def _fields(rng: random.Random) -> dict:
    """The payload's values but its key and time, from `rng`."""
    return {
        "name": rng.choice(NAMES),
        "status": rng.choice(STATUSES),
        "category": rng.choice(CATEGORIES),
        "amount": round(rng.uniform(0, 10000), 2),
        "quantity": rng.randint(0, 1000),
        "score": round(rng.uniform(0, 1), 6),
    }


def _mutation(rng: random.Random, data_ts: str) -> dict:
    """An UPDATE's SET: the time bumped and two to four payload values new."""
    fresh = _fields(rng)
    picked = sorted(rng.sample(range(len(_PAYLOAD_FIELDS)), rng.randint(2, 4)))
    return {
        "data_ts": data_ts,
        **{_PAYLOAD_FIELDS[k]: fresh[_PAYLOAD_FIELDS[k]] for k in picked},
    }


def period_end(period: int) -> date:
    """The month-end of period `period`: 0 is 2024-10-31, each one a month on."""
    year, month0 = divmod(_FIRST_MONTH + period, 12)
    return date(year, month0 + 1, calendar.monthrange(year, month0 + 1)[1])


class _Keys:
    """Per-tenant entity-id high-water marks: a new key continues its tenant's
    sequence, so it is no key the table had."""

    def __init__(self, keys) -> None:
        self._next = {t: 1 for t in TENANTS}
        for tenant, eid in keys:
            self._next[tenant] = max(self._next.get(tenant, 1), eid + 1)

    def new(self, rng: random.Random) -> Key:
        tenant = rng.choice(TENANTS)
        eid = self._next[tenant]
        self._next[tenant] = eid + 1
        return (tenant, eid)


def _next_period(
    rng: random.Random,
    live: dict[Key, dict],
    keys: _Keys,
    new_keys: int,
    stamp: Callable[[], str],
) -> dict[Key, dict]:
    """The next period's state: a tenth of the keys gone, three in ten with new
    values, `new_keys` new ones; every row read at `stamp()`."""
    out: dict[Key, dict] = {}
    for key, fields in live.items():
        roll = rng.random()
        if roll < 0.1:
            continue
        out[key] = _fields(rng) if roll < 0.4 else fields
    for _ in range(new_keys):
        out[keys.new(rng)] = _fields(rng)
    return {key: {**fields, "data_ts": stamp()} for key, fields in out.items()}


def _period_rows(state: dict[Key, dict], end: date, first_counter: int) -> list[dict]:
    return [
        {
            "sim_counter": first_counter + k,
            "tenant_id": key[0],
            "entity_id": key[1],
            "data_ts": fields["data_ts"],
            **{f: fields[f] for f in _PAYLOAD_FIELDS},
            "is_active": 1,
            "period_end": end,
        }
        for k, (key, fields) in enumerate(state.items())
    ]


def _gen_period_snapshot(n: int) -> list[dict]:
    """``n`` keys at each of three month-ends: the full state at each."""
    rng = random.Random(_BASE_SEED + 1)
    keys = _Keys([])
    rows: list[dict] = []
    live: dict[Key, dict] = {}
    for p in range(_SEED_PERIODS):
        end = period_end(p)
        start = datetime(end.year, end.month, 1)
        span = int((datetime(end.year, end.month, end.day) - start).total_seconds())

        def stamp(start=start, span=span) -> str:
            return _fmt_dt(start + timedelta(seconds=rng.randint(0, span)))

        if p == 0:
            live = {
                keys.new(rng): {**_fields(rng), "data_ts": stamp()} for _ in range(n)
            }
        else:
            live = _next_period(rng, live, keys, max(1, n // 10), stamp)
        rows.extend(_period_rows(live, end, len(rows) + 1))
    return rows


def _log_row(rng: random.Random, ordinal: int, ts: datetime, counter: int) -> dict:
    """The logs model's line `ordinal`, its time as text like every bronze
    time: what a SQL literal, a JSON message and the trail all spell alike."""
    row = app_row(rng, ordinal, ts)
    if row["ts"] is not None:
        row["ts"] = _fmt_dt(row["ts"])
    return {"sim_counter": counter, **row}


def _gen_log_lines(n: int) -> list[dict]:
    rng = random.Random(_BASE_SEED + 2)
    ts = _LOG_START
    rows = []
    for k in range(n):
        # Whole seconds: a SQL literal carries no fraction, and the table, the
        # trail and the line must say the same time.
        ts += timedelta(seconds=rng.randint(0, 4))
        rows.append(_log_row(rng, k, ts, k + 1))
    return rows


# ---- the state changes continue --------------------------------------------


def _key(row: dict) -> Key:
    return (row["tenant_id"], row["entity_id"])


class _State:
    """Every table's state after the seed and the runs replayed so far: what a
    change needs to know to continue it."""

    def __init__(self, tables: dict[str, Table], n: int) -> None:
        self.seeded = {name: len(t.rows) for name, t in tables.items()}
        self.clock = {name: _NOW for name in TABLES}
        self.inserted = dict.fromkeys(TABLES, 0)
        cdc_keys = [
            (r["@td.cdc.data.col.new.tenant_id"], r["@td.cdc.data.col.new.entity_id"])
            for r in tables[CDC].rows
        ]
        self.keys = {
            name: _Keys(cdc_keys if name == CDC else map(_key, tables[name].rows))
            for name in TABLES
            if name != LOG
        }
        # full snapshot: its rows by sim_counter, in order -- its file.
        self.full = {r["sim_counter"]: dict(r) for r in tables[FULL].rows}
        # soft delete: each row's key; the keys not (soft-)deleted.
        self.soft_rows: dict[int, Key] = {}
        self.soft_alive: dict[Key, None] = {}
        for r in tables[SOFT].rows:
            self.soft_rows[r["sim_counter"]] = _key(r)
            if r["deleted"]:
                self.soft_alive.pop(_key(r), None)
            else:
                self.soft_alive[_key(r)] = None
        # no delete: each row's key; how many rows each key has.
        self.nd_rows: dict[int, Key] = {}
        self.nd_count: dict[Key, int] = {}
        for r in tables[NO_DELETE].rows:
            self.nd_rows[r["sim_counter"]] = _key(r)
            self.nd_count[_key(r)] = self.nd_count.get(_key(r), 0) + 1
        # cdc: each live key's last new image.
        self.live: dict[Key, dict] = {}
        for r, key in zip(tables[CDC].rows, cdc_keys, strict=True):
            if r["@td.cdc.meta.op"] == "d":
                self.live.pop(key, None)
            else:
                self.live[key] = {
                    col: r[f"@td.cdc.data.col.new.{col}"] for col, _ in SOURCE_COLS
                }
        self.tx_id, self.tx_seq, self.tx_left = "", 0, 0
        # period snapshot: the last period's state.
        self.period = _SEED_PERIODS - 1
        self.period_keys = n
        last = period_end(self.period)
        self.period_live = {
            _key(r): {f: r[f] for f in ("data_ts", *_PAYLOAD_FIELDS)}
            for r in tables[PERIOD].rows
            if r["period_end"] == last
        }
        self.new_periods: list[Table] = []
        # log: the lines so far, and the time the next one follows.
        self.log_lines = len(tables[LOG].rows)
        self.log_clock = _NOW

    def begin_run(self) -> None:
        """A run's CDC rows open a transaction of their own; its new periods
        are the ones it restages."""
        self.tx_left = 0
        self.new_periods = []

    def tick(self, table: str) -> str:
        self.clock[table] += timedelta(seconds=1)
        return _fmt_dt(self.clock[table])

    def counter(self, table: str) -> int:
        self.inserted[table] += 1
        return _INSERT_BASE + self.inserted[table]

    def payload(self, rng: random.Random, table: str, key: Key) -> dict:
        return {
            "tenant_id": key[0],
            "entity_id": key[1],
            "data_ts": self.tick(table),
            **_fields(rng),
        }


def _find(present: Callable[[int], bool], start: int, seeded: int, step: int):
    """The seeded row nearest `start` (a sim_counter) in the direction of
    `step` that is still `present`, wrapping round; ``None`` when none is."""
    sc = start
    for _ in range(seeded):
        if present(sc):
            return sc
        sc += step
        if sc < 1:
            sc = seeded
        elif sc > seeded:
            sc = 1
    return None


class _BronzeEntity(Entity):
    rows_per_set = 10

    def __init__(self, model: _Bronze, table: str) -> None:
        self._model = model
        self.table = table
        self.columns = _columns(table)

    @property
    def st(self) -> _State:
        return self._model.state


class _FullSnapshot(_BronzeEntity):
    """A new key; a row's values changed in place; a row deleted. Its file is
    the state (``snapshot``)."""

    snapshot = True

    def new_rows(self, rng, i):
        st = self.st
        key = st.keys[FULL].new(rng)
        row = {"sim_counter": st.counter(FULL), **st.payload(rng, FULL, key)}
        row["is_active"] = 1
        st.full[row["sim_counter"]] = row
        return [dict(row)]

    def pick(self, kind, rng, i, existing):
        st = self.st
        step = 1 if kind is OpKind.UPDATE else -1
        sc = _find(st.full.__contains__, i + 1, st.seeded[FULL], step)
        if sc is None:
            return None
        if kind is OpKind.DELETE:
            del st.full[sc]
            return {"sim_counter": sc}, None
        set_values = _mutation(rng, st.tick(FULL))
        st.full[sc].update(set_values)
        return {"sim_counter": sc}, set_values


class _SoftDelete(_BronzeEntity):
    """A change row: a new version of a live key (six in ten), a new key (two),
    a key's deletion, flagged (two); an UPDATE changes a live key's row in
    place, and one in five flags it deleted. Never a physical DELETE."""

    supports = (OpKind.INSERT, OpKind.UPDATE)

    def new_rows(self, rng, i):
        st = self.st
        alive = st.soft_alive
        roll = rng.random()
        deleted = 0
        if alive and roll < 0.6:
            key = rng.choice(list(alive))
        elif not alive or roll < 0.8:
            key = st.keys[SOFT].new(rng)
            alive[key] = None
        else:
            key = rng.choice(list(alive))
            del alive[key]
            deleted = 1
        row = {"sim_counter": st.counter(SOFT), **st.payload(rng, SOFT, key)}
        row["deleted"] = deleted
        st.soft_rows[row["sim_counter"]] = key
        return [row]

    def pick(self, kind, rng, i, existing):
        st = self.st

        def live(sc: int) -> bool:
            return st.soft_rows.get(sc) in st.soft_alive

        sc = _find(live, i + 1, st.seeded[SOFT], 1)
        if sc is None:
            return None
        set_values = _mutation(rng, st.tick(SOFT))
        if rng.random() < 0.2:
            set_values["deleted"] = 1
            del st.soft_alive[st.soft_rows[sc]]
        return {"sim_counter": sc}, set_values


class _NoDelete(_BronzeEntity):
    """A change row: a new version of a key that has a row (half), else a new
    key; a row changed in place; a row deleted, which no cursor sees."""

    def new_rows(self, rng, i):
        st = self.st
        if st.nd_count and rng.random() < 0.5:
            key = rng.choice(list(st.nd_count))
        else:
            key = st.keys[NO_DELETE].new(rng)
        row = {"sim_counter": st.counter(NO_DELETE), **st.payload(rng, NO_DELETE, key)}
        row["is_active"] = 1
        st.nd_rows[row["sim_counter"]] = key
        st.nd_count[key] = st.nd_count.get(key, 0) + 1
        return [row]

    def pick(self, kind, rng, i, existing):
        st = self.st
        step = 1 if kind is OpKind.UPDATE else -1
        sc = _find(st.nd_rows.__contains__, i + 1, st.seeded[NO_DELETE], step)
        if sc is None:
            return None
        if kind is OpKind.DELETE:
            key = st.nd_rows.pop(sc)
            st.nd_count[key] -= 1
            if not st.nd_count[key]:
                del st.nd_count[key]
            return {"sim_counter": sc}, None
        return {"sim_counter": sc}, _mutation(rng, st.tick(NO_DELETE))


class _CdcStream(_BronzeEntity):
    """The stream continued: ``i`` for a new key, ``u`` and ``d`` for a live
    one, ``old`` its last ``new``; a delete's row state in ``new``, ``old``
    null; transactions of one to three rows."""

    supports = (OpKind.INSERT,)

    def new_rows(self, rng, i):
        st = self.st
        if st.tx_left == 0:
            st.tx_id, st.tx_seq, st.tx_left = _new_tx_id(rng), 1, rng.randint(1, 3)
        else:
            st.tx_seq += 1
        st.tx_left -= 1
        roll = rng.random()
        old = None
        if not st.live or roll < 0.4:
            op = "i"
            key = st.keys[CDC].new(rng)
            new = {**st.payload(rng, CDC, key), "is_active": 1}
            st.live[key] = new
        elif roll < 0.8:
            op = "u"
            key = rng.choice(list(st.live))
            old = st.live[key]
            new = {**st.payload(rng, CDC, key), "is_active": 1}
            st.live[key] = new
        else:
            op = "d"
            key = rng.choice(list(st.live))
            new = st.live.pop(key)
        row: dict = {
            "sim_counter": st.counter(CDC),
            "@td.cdc.meta.op": op,
            "@td.cdc.meta.tx": st.tx_id,
            "@td.cdc.meta.sq": st.tx_seq,
        }
        for col, _ in SOURCE_COLS:
            row[f"@td.cdc.data.col.old.{col}"] = old[col] if old else None
            row[f"@td.cdc.data.col.new.{col}"] = new[col]
        return [row]


class _AppendEvents(_BronzeEntity):
    """A new event: the next of its tenant's sequence. Events never change."""

    supports = (OpKind.INSERT,)

    def new_rows(self, rng, i):
        st = self.st
        key = st.keys[APPEND].new(rng)
        row = {"sim_counter": st.counter(APPEND), **st.payload(rng, APPEND, key)}
        row["is_active"] = 1
        return [row]


class _PeriodSnapshot(_BronzeEntity):
    """One INSERT is the next period: every key still there at the next
    month-end, some with new values, some gone, some new -- each row read a
    second after the last."""

    supports = (OpKind.INSERT,)
    snapshot = True
    rows_per_set = 1

    def new_rows(self, rng, i):
        st = self.st
        st.period += 1
        end = period_end(st.period)
        st.period_live = _next_period(
            rng,
            st.period_live,
            st.keys[PERIOD],
            max(1, st.period_keys // 10),
            lambda: st.tick(PERIOD),
        )
        rows = _period_rows(st.period_live, end, _INSERT_BASE + st.inserted[PERIOD] + 1)
        st.inserted[PERIOD] += len(rows)
        st.new_periods.append(Table(PERIOD, self.columns, [dict(r) for r in rows]))
        return rows


class _LogLines(_BronzeEntity):
    """The log's next line (a stack-trace continuation every 25th, as the
    ``logs`` model writes them), one to four seconds after the last."""

    supports = (OpKind.INSERT,)

    def new_rows(self, rng, i):
        st = self.st
        st.log_clock += timedelta(seconds=rng.randint(1, 4))
        ordinal = st.log_lines
        st.log_lines += 1
        return [_log_row(rng, ordinal, st.log_clock, st.counter(LOG))]


class _Bronze(Model):
    replays = True
    kafka_recipe = True

    def __init__(self) -> None:
        self.entities = [
            _FullSnapshot(self, FULL),
            _SoftDelete(self, SOFT),
            _NoDelete(self, NO_DELETE),
            _CdcStream(self, CDC),
            _AppendEvents(self, APPEND),
            _PeriodSnapshot(self, PERIOD),
            _LogLines(self, LOG),
        ]
        self._state: _State | None = None

    @property
    def state(self) -> _State:
        if self._state is None:
            raise RuntimeError("bronze: a change planned before prepare()")
        return self._state

    def prepare(self, ctx: PlanContext) -> None:
        """The seed's state, then every earlier run planned again on it."""
        n = BASE_SIZE * ctx.size
        tables = self.build_initial(random.Random(INITIAL_SEED), n)
        self._state = _State({t.name: t for t in tables}, n)
        for spec in ctx.history:
            self._state.begin_run()
            ctx.replan(self, spec)
        self._state.begin_run()

    def restage(self, tables: set[str]) -> dict[str, list[Table]]:
        st = self.state
        out: dict[str, list[Table]] = {}
        if FULL in tables:
            out[FULL] = [
                Table(FULL, _columns(FULL), [dict(r) for r in st.full.values()])
            ]
        if PERIOD in tables and st.new_periods:
            out[PERIOD] = list(st.new_periods)
        return out

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        random.seed(_BASE_SEED)
        batches = n
        batch_size = _BATCH_SIZE  # 100 rows a batch, whatever the size
        now, span = _NOW, _SPAN
        return [
            Table(
                FULL, _columns(FULL), _gen_full_snapshot(batches, batch_size, now, span)
            ),
            Table(
                SOFT,
                _columns(SOFT),
                _gen_insup_soft_delete(batches, batch_size, now, span),
            ),
            Table(
                NO_DELETE,
                _columns(NO_DELETE),
                _gen_insup_no_delete(batches, batch_size, now, span),
            ),
            Table(CDC, _columns(CDC), _gen_cdc_stream(batches, batch_size, now, span)),
            Table(
                APPEND,
                _columns(APPEND),
                _gen_append_events(batches, batch_size, now, span),
            ),
            Table(PERIOD, _columns(PERIOD), _gen_period_snapshot(n)),
            Table(LOG, _columns(LOG), _gen_log_lines(n * batch_size)),
        ]


def datagenerator() -> Model:
    return _Bronze()
