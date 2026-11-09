#
# Copyright 2026 Tabsdata Inc.
#

"""Data generator for the ``logs`` model: two log files, one line per row.

  app     an application log, ``<ISO time> <LEVEL> [<service>] req=<id>
          latency_ms=<n|-> <message>``; every 25th line is the ``at ...``
          continuation of a stack trace, which that pattern does not match --
          a real log has them, and a grok over it must leave them null
  access  the Apache/nginx combined log format, documentation addresses
          (RFC 5737) and an English month whatever the machine's locale

Each table's ``line`` column (``log_line``) is the text: a file domain stages a
log table as ``log/<entity>_<stamp>.log`` and in no other format. The other
columns are what the line says -- null where it says nothing, a ``-`` field or
a continuation line -- and travel only in the ``--emit-ops`` trail, so a check
compares what a parser made of the lines with what they were made from. On a
kafka domain a row is a JSON message like any other model's.

Insert-only: a log appends. An insert's line is stamped a second per ordinal
from 2026-03-01, after every seeded line of any size up to a million rows.
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from typing import ClassVar

from tabsdata_dev.common.systems.datagen import Entity, Model, OpKind
from tabsdata_dev.common.systems.emit import Column, Table

_SEED_START = datetime(2026, 1, 1)
_INSERT_START = datetime(2026, 3, 1)
_CONTINUATION_EVERY = 25

_MONTHS = (
    "Jan",
    "Feb",
    "Mar",
    "Apr",
    "May",
    "Jun",
    "Jul",
    "Aug",
    "Sep",
    "Oct",
    "Nov",
    "Dec",
)

_LEVELS = ("DEBUG", "INFO", "INFO", "INFO", "WARN", "ERROR")
_SERVICES = ("checkout", "catalog", "auth", "payments", "search")
_MESSAGES = {
    "DEBUG": ("cache lookup", "retrying connection", "loaded config"),
    "INFO": ("request served", "order placed", "user signed in", "item indexed"),
    "WARN": ("slow upstream", "token near expiry", "queue depth high"),
    "ERROR": ("upstream timeout", "payment declined", "unhandled exception"),
}
_FRAMES = (
    "com.example.checkout.Cart.place(Cart.java:88)",
    "com.example.payments.Gateway.charge(Gateway.java:142)",
    "com.example.auth.Session.refresh(Session.java:57)",
)

_USERS = ("alice", "bob", "carol", "dave")
_METHODS = ("GET", "GET", "GET", "POST", "PUT", "DELETE")
_PATHS = ("/", "/cart", "/checkout", "/search?q=lamp", "/item/1042", "/login")
_STATUSES = (200, 200, 200, 201, 204, 301, 304, 404, 500)
_REFERRERS = ("https://shop.example/", "https://search.example/?q=shop")
_AGENTS = (
    "Mozilla/5.0 (X11; Linux x86_64) Gecko/20100101 Firefox/131.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_6) Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/130.0",
    "curl/8.7.1",
)

_APP_COLUMNS = [
    Column("ts", "timestamp"),
    Column("level", "varchar(5)"),
    Column("service", "varchar(16)"),
    Column("request_id", "char(12)"),
    Column("latency_ms", "int"),
    Column("message", "varchar(200)"),
    Column("line", "text", nullable=False, log_line=True),
]

_ACCESS_COLUMNS = [
    Column("client_ip", "varchar(15)", nullable=False),
    Column("user_name", "varchar(16)"),
    Column("ts", "timestamp", nullable=False),
    Column("method", "varchar(7)", nullable=False),
    Column("path", "varchar(100)", nullable=False),
    Column("protocol", "varchar(8)", nullable=False),
    Column("status", "smallint", nullable=False),
    Column("bytes", "int"),
    Column("referrer", "varchar(100)"),
    Column("user_agent", "varchar(120)", nullable=False),
    Column("line", "text", nullable=False, log_line=True),
]


def _iso_ms(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%S.") + f"{ts.microsecond // 1000:03d}Z"


def _clf_time(ts: datetime) -> str:
    """``01/Jan/2026:00:00:01 +0000``, the month spelled from a table: strftime's
    ``%b`` is the locale's."""
    return (
        f"{ts.day:02d}/{_MONTHS[ts.month - 1]}/{ts.year}:"
        f"{ts.strftime('%H:%M:%S')} +0000"
    )


def app_row(rng: random.Random, ordinal: int, ts: datetime) -> dict:
    """Line `ordinal` of the application log, at `ts`."""
    if ordinal % _CONTINUATION_EVERY == _CONTINUATION_EVERY - 1:
        frame = rng.choice(_FRAMES)
        return {
            "ts": None,
            "level": None,
            "service": None,
            "request_id": None,
            "latency_ms": None,
            "message": None,
            "line": f"    at {frame}",
        }
    level = rng.choice(_LEVELS)
    service = rng.choice(_SERVICES)
    request_id = f"{rng.getrandbits(48):012x}"
    latency = None if level == "DEBUG" else rng.randint(1, 2500)
    message = rng.choice(_MESSAGES[level])
    line = (
        f"{_iso_ms(ts)} {level} [{service}] req={request_id} "
        f"latency_ms={'-' if latency is None else latency} {message}"
    )
    return {
        "ts": ts,
        "level": level,
        "service": service,
        "request_id": request_id,
        "latency_ms": latency,
        "message": message,
        "line": line,
    }


def access_row(rng: random.Random, ordinal: int, ts: datetime) -> dict:
    """Line `ordinal` of the access log, at `ts`."""
    net = rng.choice(("192.0.2", "198.51.100", "203.0.113"))
    ip = f"{net}.{rng.randint(1, 254)}"
    user = rng.choice((None, None, *_USERS))
    method = rng.choice(_METHODS)
    path = rng.choice(_PATHS)
    status = rng.choice(_STATUSES)
    size = None if status in (204, 304) else rng.randint(120, 48000)
    referrer = rng.choice((None, *_REFERRERS))
    agent = rng.choice(_AGENTS)
    line = (
        f"{ip} - {user or '-'} [{_clf_time(ts)}] "
        f'"{method} {path} HTTP/1.1" {status} {"-" if size is None else size} '
        f'"{referrer or "-"}" "{agent}"'
    )
    return {
        "client_ip": ip,
        "user_name": user,
        "ts": ts,
        "method": method,
        "path": path,
        "protocol": "HTTP/1.1",
        "status": status,
        "bytes": size,
        "referrer": referrer,
        "user_agent": agent,
        "line": line,
    }


class _App(Entity):
    table = "app"
    columns = _APP_COLUMNS
    supports = (OpKind.INSERT,)

    def new_row(self, rng: random.Random, i: int) -> dict:
        return app_row(rng, i, _INSERT_START + timedelta(seconds=i))


class _Access(Entity):
    table = "access"
    columns = _ACCESS_COLUMNS
    supports = (OpKind.INSERT,)

    def new_row(self, rng: random.Random, i: int) -> dict:
        return access_row(rng, i, _INSERT_START + timedelta(seconds=i))


class _Logs(Model):
    entities: ClassVar[list[Entity]] = [_App(), _Access()]

    def build_initial(self, rng: random.Random, n: int) -> list[Table]:
        # Up to a few seconds between lines, in order, so every size up to a
        # million lines stays inside the two months before the inserts' first
        # second. The app log is stamped to the millisecond, the access log to
        # the second, as their formats are.
        app, access = [], []
        ts = _SEED_START
        for k in range(n):
            ts += timedelta(milliseconds=rng.randint(0, 4000))
            app.append(app_row(rng, k, ts))
        ts = _SEED_START
        for k in range(n):
            ts += timedelta(seconds=rng.randint(0, 4))
            access.append(access_row(rng, k, ts))
        return [
            Table("app", _APP_COLUMNS, app),
            Table("access", _ACCESS_COLUMNS, access),
        ]


def datagenerator() -> Model:
    return _Logs()
