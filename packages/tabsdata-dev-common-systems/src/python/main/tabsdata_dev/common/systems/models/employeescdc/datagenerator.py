#
# Copyright 2026 Tabsdata Inc.
#

"""employeescdc — the ways a row is identified that a CDC stream has to get right.

Built for the CDC suites, whose employees model changes rows only by a plain
single-column key that never changes. Here each table is one way a row is named:

  * ``accounts`` -- a single-column primary key that the changes CHANGE: every
    UPDATE moves ``account_id`` to a new value (and renames the owner), so a
    stream has to carry the old key in its before-image and the new one in its
    row.
  * ``ledger``   -- a composite primary key (``account_code``, ``entry_no``);
    updates and deletes name a row by both columns.
  * ``devices``  -- no primary key; a UNIQUE index on ``serial`` names a row.
  * ``readings`` -- no primary key and no index at all; ``reading_id`` is unique
    only because this generator makes it so, and the database knows nothing of
    it.
  * ``audit``    -- a plain primary key, changed like the others but tracked by no
    stream the CDC suites register: the database is busy with a table the stream
    must leave out, and a stream that carries it, or stalls on it, is wrong.

No table references another, so a key change is never refused by a foreign key
and a delete cascades nowhere: what the stream carries is exactly the trail.

Every entity takes inserts, updates and deletes, one row per set, so a ``--ops
Mix`` set is one transaction touching all five tables with one verb. A seeded
row ``i`` (0-based) is named by ``target``; inserted rows take keys from their
own range (``_INSERT_BASE`` on), which no seeded key reaches, and a rekeyed
account moves ``_REKEY_OFFSET`` up, past both.
"""

from __future__ import annotations

import random
from datetime import date, timedelta
from decimal import Decimal
from typing import ClassVar

from tabsdata_dev.common.systems.datagen import Entity, Model
from tabsdata_dev.common.systems.emit import Column, Table

_SEED_BASE = 1
_INSERT_BASE = 9_000_000
_REKEY_OFFSET = 50_000_000
# Ledger entries per account code: seeded entry i is (code i // N, entry i % N).
_ENTRIES_PER_CODE = 10
_EPOCH = date(2020, 1, 1)
_STATUSES = ("active", "idle", "retired")
_ACTIONS = ("login", "logout", "export", "approve")

_ACCOUNTS_COLS = [
    Column("account_id", "int", nullable=False),
    Column("owner", "varchar(40)", nullable=False),
    Column("balance", "decimal(12,2)", nullable=False),
    Column("opened_on", "date", nullable=False),
]
_LEDGER_COLS = [
    Column("account_code", "varchar(12)", nullable=False),
    Column("entry_no", "int", nullable=False),
    Column("amount", "decimal(12,2)", nullable=False),
    Column("memo", "varchar(40)", nullable=False),
    Column("booked_on", "date", nullable=False),
]
_DEVICES_COLS = [
    Column("serial", "varchar(20)", nullable=False),
    Column("model", "varchar(20)", nullable=False),
    Column("status", "varchar(10)", nullable=False),
    Column("firmware", "int", nullable=False),
]
_AUDIT_COLS = [
    Column("audit_id", "int", nullable=False),
    Column("actor", "varchar(40)", nullable=False),
    Column("action", "varchar(20)", nullable=False),
    Column("noted_on", "date", nullable=False),
]
_READINGS_COLS = [
    Column("reading_id", "int", nullable=False),
    Column("device_serial", "varchar(20)", nullable=False),
    Column("reading", "decimal(10,3)", nullable=False),
    Column("taken_on", "date", nullable=False),
]


def _code(n: int) -> str:
    return f"AC{n:08d}"


def _serial(n: int) -> str:
    return f"SN{n:010d}"


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return Decimal(rng.randint(low * 100, high * 100)) / 100


def _reading(rng: random.Random) -> Decimal:
    return Decimal(rng.randint(0, 999_999)) / 1000


class _Accounts(Entity):
    """An UPDATE changes the key: the before-image carries the old one."""

    table = "accounts"
    columns = _ACCOUNTS_COLS

    def new_row(self, rng: random.Random, i: int) -> dict:
        return {
            "account_id": _INSERT_BASE + i,
            "owner": f"New owner {i}"[:40],
            "balance": Decimal("0.00"),
            "opened_on": _EPOCH,
        }

    def target(self, i: int, existing: int) -> dict:
        return {"account_id": _SEED_BASE + i}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {
            "account_id": _REKEY_OFFSET + _SEED_BASE + i,
            "owner": f"Rekeyed {i}"[:40],
        }


class _Ledger(Entity):
    """A composite key: both columns name the row."""

    table = "ledger"
    columns = _LEDGER_COLS

    def new_row(self, rng: random.Random, i: int) -> dict:
        return {
            "account_code": _code(_INSERT_BASE + i),
            "entry_no": 0,
            "amount": _money(rng, 1, 500),
            "memo": f"posted {i}"[:40],
            "booked_on": _EPOCH,
        }

    def target(self, i: int, existing: int) -> dict:
        return {
            "account_code": _code(i // _ENTRIES_PER_CODE),
            "entry_no": i % _ENTRIES_PER_CODE,
        }

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"amount": _money(rng, 1, 500), "memo": f"adjusted {i}"[:40]}


class _Devices(Entity):
    """No primary key: the unique ``serial`` names the row."""

    table = "devices"
    columns = _DEVICES_COLS

    def new_row(self, rng: random.Random, i: int) -> dict:
        return {
            "serial": _serial(_INSERT_BASE + i),
            "model": "X-new",
            "status": "active",
            "firmware": 1,
        }

    def target(self, i: int, existing: int) -> dict:
        return {"serial": _serial(i)}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"status": _STATUSES[i % len(_STATUSES)], "firmware": 100 + i}


class _Readings(Entity):
    """No key and no index: ``reading_id`` is unique by construction alone."""

    table = "readings"
    columns = _READINGS_COLS

    def new_row(self, rng: random.Random, i: int) -> dict:
        return {
            "reading_id": _INSERT_BASE + i,
            "device_serial": _serial(_INSERT_BASE + i),
            "reading": _reading(rng),
            "taken_on": _EPOCH,
        }

    def target(self, i: int, existing: int) -> dict:
        return {"reading_id": _SEED_BASE + i}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"reading": _reading(rng)}


class _Audit(Entity):
    """A plain key, on a table no CDC suite's stream tracks."""

    table = "audit"
    columns = _AUDIT_COLS

    def new_row(self, rng: random.Random, i: int) -> dict:
        return {
            "audit_id": _INSERT_BASE + i,
            "actor": f"actor {i}"[:40],
            "action": _ACTIONS[i % len(_ACTIONS)],
            "noted_on": _EPOCH,
        }

    def target(self, i: int, existing: int) -> dict:
        return {"audit_id": _SEED_BASE + i}

    def mutate(self, rng: random.Random, i: int, existing: int) -> dict:
        return {"action": _ACTIONS[(i + 1) % len(_ACTIONS)], "actor": f"reviewed {i}"}


def _gen_audit(rng: random.Random, n: int) -> list[dict]:
    return [
        {
            "audit_id": _SEED_BASE + i,
            "actor": f"actor {i}",
            "action": _ACTIONS[i % len(_ACTIONS)],
            "noted_on": _EPOCH + timedelta(days=i % 700),
        }
        for i in range(n)
    ]


def _gen_accounts(rng: random.Random, n: int) -> list[dict]:
    return [
        {
            "account_id": _SEED_BASE + i,
            "owner": f"Owner {i}",
            "balance": _money(rng, 0, 100_000),
            "opened_on": _EPOCH + timedelta(days=i % 2000),
        }
        for i in range(n)
    ]


def _gen_ledger(rng: random.Random, n: int) -> list[dict]:
    return [
        {
            "account_code": _code(i // _ENTRIES_PER_CODE),
            "entry_no": i % _ENTRIES_PER_CODE,
            "amount": _money(rng, 1, 5_000),
            "memo": f"entry {i}",
            "booked_on": _EPOCH + timedelta(days=i % 1000),
        }
        for i in range(n)
    ]


def _gen_devices(rng: random.Random, n: int) -> list[dict]:
    return [
        {
            "serial": _serial(i),
            "model": f"X-{i % 7}",
            "status": "active",
            "firmware": rng.randint(1, 50),
        }
        for i in range(n)
    ]


def _gen_readings(rng: random.Random, n: int) -> list[dict]:
    return [
        {
            "reading_id": _SEED_BASE + i,
            "device_serial": _serial(i),
            "reading": _reading(rng),
            "taken_on": _EPOCH + timedelta(days=i % 500),
        }
        for i in range(n)
    ]


class _EmployeesCdcModel(Model):
    entities: ClassVar[list[Entity]] = [
        _Accounts(),
        _Ledger(),
        _Devices(),
        _Readings(),
        _Audit(),
    ]

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        return [
            Table("accounts", _ACCOUNTS_COLS, _gen_accounts(rng, n)),
            Table("ledger", _LEDGER_COLS, _gen_ledger(rng, n)),
            Table("devices", _DEVICES_COLS, _gen_devices(rng, n)),
            Table("readings", _READINGS_COLS, _gen_readings(rng, n)),
            Table("audit", _AUDIT_COLS, _gen_audit(rng, n)),
        ]


def datagenerator() -> Model:
    return _EmployeesCdcModel()
