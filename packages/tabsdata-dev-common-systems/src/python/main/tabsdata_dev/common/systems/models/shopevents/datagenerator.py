#
# Copyright 2026 Tabsdata Inc.
#

"""Data generator for the ``shopevents`` model: a web shop's event streams.

  page_view     a page seen, keyed by ``view_id``           -> Avro messages
  order_placed  an order, keyed by ``order_id``             -> Protobuf messages

The wire formats are the model's (``model.json``'s ``message_formats``): on a
kafka domain each topic's messages are encoded with the schema its columns make
(``redpanda/wire.py``); on a file domain they are tables like any other. The
columns cover what the two encodings have to map -- nulls, a boolean, a decimal,
a date and a timestamp -- so a consumer of either sees each kind once.

Insert-only: an event stream appends. An insert's key is 10,000,000 + its
ordinal, past every seeded key, and its time a second per ordinal from
2026-03-01.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import ClassVar

from tabsdata_dev.common.systems.datagen import Entity, Model, OpKind
from tabsdata_dev.common.systems.emit import Column, Table

_SEED_START = datetime(2026, 1, 1)
_INSERT_START = datetime(2026, 3, 1)
_INSERT_BASE = 10_000_000

_PAGES = ("/", "/cart", "/checkout", "/search", "/item/1042", "/item/2077")
_REFERRERS = ("https://search.example/", "https://social.example/post/9")
_CURRENCIES = ("USD", "EUR", "GBP")
_COUPONS = ("WELCOME10", "SPRING", "FREESHIP")

_PAGE_VIEW_COLUMNS = [
    Column("view_id", "bigint", nullable=False),
    Column("session_id", "char(12)", nullable=False),
    Column("user_id", "int"),
    Column("page", "varchar(100)", nullable=False),
    Column("referrer", "varchar(100)"),
    Column("viewed_at", "timestamp", nullable=False),
    Column("duration_ms", "int", nullable=False),
    Column("bounced", "boolean", nullable=False),
]

_ORDER_COLUMNS = [
    Column("order_id", "bigint", nullable=False),
    Column("user_id", "int", nullable=False),
    Column("items", "smallint", nullable=False),
    Column("total", "decimal(10,2)", nullable=False),
    Column("currency", "char(3)", nullable=False),
    Column("coupon", "varchar(16)"),
    Column("placed_at", "timestamp", nullable=False),
    Column("ship_by", "date", nullable=False),
]


def page_view(rng: random.Random, view_id: int, ts: datetime) -> dict:
    return {
        "view_id": view_id,
        "session_id": f"{rng.getrandbits(48):012x}",
        "user_id": rng.choice((None, rng.randint(1, 5000))),
        "page": rng.choice(_PAGES),
        "referrer": rng.choice((None, *_REFERRERS)),
        "viewed_at": ts,
        "duration_ms": rng.randint(50, 120_000),
        "bounced": rng.random() < 0.3,
    }


def order_placed(rng: random.Random, order_id: int, ts: datetime) -> dict:
    items = rng.randint(1, 12)
    return {
        "order_id": order_id,
        "user_id": rng.randint(1, 5000),
        "items": items,
        "total": round(items * rng.uniform(3, 250), 2),
        "currency": rng.choice(_CURRENCIES),
        "coupon": rng.choice((None, None, *_COUPONS)),
        "placed_at": ts,
        "ship_by": (ts + timedelta(days=rng.randint(1, 7))).date(),
    }


class _PageView(Entity):
    table = "page_view"
    columns = _PAGE_VIEW_COLUMNS
    supports = (OpKind.INSERT,)

    def new_row(self, rng: random.Random, i: int) -> dict:
        return page_view(rng, _INSERT_BASE + i, _INSERT_START + timedelta(seconds=i))


class _OrderPlaced(Entity):
    table = "order_placed"
    columns = _ORDER_COLUMNS
    supports = (OpKind.INSERT,)

    def new_row(self, rng: random.Random, i: int) -> dict:
        return order_placed(rng, _INSERT_BASE + i, _INSERT_START + timedelta(seconds=i))


class _ShopEvents(Model):
    entities: ClassVar[list[Entity]] = [_PageView(), _OrderPlaced()]

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        views = [
            page_view(rng, k + 1, _SEED_START + timedelta(seconds=3 * k))
            for k in range(n)
        ]
        # An order for every tenth view: fewer orders than views, as in a shop.
        orders = [
            order_placed(rng, k + 1, _SEED_START + timedelta(seconds=30 * k))
            for k in range(max(1, n // 10))
        ]
        return [
            Table("page_view", _PAGE_VIEW_COLUMNS, views),
            Table("order_placed", _ORDER_COLUMNS, orders),
        ]


def datagenerator() -> Model:
    return _ShopEvents()
