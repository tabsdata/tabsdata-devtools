#
# Copyright 2026 Tabsdata Inc.
#
"""A suite run's identity: ``XP_ID`` and the ``XP_SHORT_ID`` derived with it.

``XP_ID`` is ``xp_<USER>_<BUILD>_<YYYYMMDD>T<hhmmss>`` (UTC): tabsdata-os's
build identity -- ``$TD_BUILD_USER``, else the OS login, and
``$TD_BUILD_NUMBER``, else ``0`` -- and the second the run began. It names the
run's domains (``${xp_name(x)}`` is ``<XP_ID>_x``) and, by default, the suite
run and its project.

``XP_SHORT_ID`` is the same identity in 12 characters, ``<UUU><BB>_<TTTTTT>``,
for the names a run leaves inside external systems, where identifiers are
short (Postgres stops at 63 bytes): the user's first 3 characters, the
build's last 2 digits and the seconds since 2026-01-01T00:00:00Z in base 36,
6 wide -- until 2094, and sorting as the runs did. Lower case only: Postgres
folds an unquoted name to lower case and DB2, Oracle and Snowflake to upper,
so a mixed-case alphabet would make two seconds one name. Rejected: one
base-62 character per field (``a`` and ``A`` fold together), and
``(YYYY-2026)MMDDhhmmss`` as one number in base 36 (7 characters from 2027).

Two runs one process starts are a second apart at least (`new`): a suite dir's
lanes each get an ID of their own as they are created.
"""

from __future__ import annotations

import getpass
import os
import re
import threading
import time
from datetime import datetime, timezone

EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)
DIGITS = "0123456789abcdefghijklmnopqrstuvwxyz"
SHORT_TIME_WIDTH = 6
#: What a suite reads as when no run is behind it (list-suites, list-systems):
#: the shape of a real ID, so the names it makes are the shape of real ones.
PLACEHOLDER = ("xp_user_0_20260101T000000", "use00_000000")

# Looked up at call time, so a test can run the clock.
clock = time.time
sleep = time.sleep

_lock = threading.Lock()
_last = -1


def _token(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "x"


def build_user() -> str:
    """``$TD_BUILD_USER``, else the OS login, as an identifier token."""
    try:
        login = getpass.getuser()
    except Exception:  # noqa: BLE001 -- no controlling user (odd CI)
        login = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    return _token(os.environ.get("TD_BUILD_USER") or login)


def build_number() -> str:
    """``$TD_BUILD_NUMBER``, else ``0``, as an identifier token."""
    return _token(os.environ.get("TD_BUILD_NUMBER") or "0")


def base36(n: int, width: int) -> str:
    out = ""
    while n:
        n, d = divmod(n, 36)
        out = DIGITS[d] + out
    return out.rjust(width, "0")


def make(user: str, build: str, seconds: int) -> tuple[str, str]:
    """``(XP_ID, XP_SHORT_ID)`` of a run begun at `seconds` (since the epoch)."""
    when = datetime.fromtimestamp(seconds, tz=timezone.utc)
    xp_id = f"xp_{user}_{build}_{when:%Y%m%dT%H%M%S}"
    uuu = re.sub(r"[^a-z0-9]", "", user.lower())[:3].ljust(3, "x")
    bb = (re.sub(r"[^0-9]", "", build)[-2:] or "0").rjust(2, "0")
    since = int((when - EPOCH).total_seconds())
    if since < 0:
        raise ValueError(f"{when:%Y-%m-%d} is before {EPOCH:%Y-%m-%d}")
    return xp_id, f"{uuu}{bb}_{base36(since, SHORT_TIME_WIDTH)}"


def new() -> tuple[str, str]:
    """A fresh ``(XP_ID, XP_SHORT_ID)``, a second after the last this process
    made: two runs it starts never share one."""
    global _last
    with _lock:
        now = int(clock())
        while now <= _last:
            sleep(_last + 1 - clock())
            now = int(clock())
        _last = now
    return make(build_user(), build_number(), now)


# ------------------------------------------------------------ resolving ----
XP_NAME_RE = re.compile(r"\$\{xp_name\(([^)]*)\)\}")
_NAME_ARG = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
RUN_TOKENS = {"XP_ID": 0, "XP_SHORT_ID": 1}


def resolve(value, xp_id: str, short_id: str, where: str = "suite"):
    """`value` -- a suite, as parsed JSON -- with every ``${xp_name(x)}``,
    ``${XP_ID}`` and ``${XP_SHORT_ID}`` in its strings replaced. The tokens a
    run fills in as it goes (``${XP_WORK_DIR}``, ``${XP_PROJECT}``) are left
    for it. A malformed ``${xp_name(...)}`` is refused, not left to name a
    domain nobody meant."""
    if isinstance(value, list):
        return [resolve(v, xp_id, short_id, where) for v in value]
    if isinstance(value, dict):
        return {k: resolve(v, xp_id, short_id, where) for k, v in value.items()}
    if not isinstance(value, str):
        return value

    def name(m: re.Match) -> str:
        arg = m.group(1).strip()
        if not _NAME_ARG.match(arg):
            raise ValueError(
                f"{where}: ${{xp_name({m.group(1)})}}: a name is a letter or digit, "
                "then letters, digits, '_' or '-'"
            )
        return f"{xp_id}_{arg}"

    out = XP_NAME_RE.sub(name, value)
    for token, i in RUN_TOKENS.items():
        out = out.replace(f"${{{token}}}", (xp_id, short_id)[i])
    if "${xp_name" in out:
        raise ValueError(
            f"{where}: {value!r} has a ${{xp_name(...)}} that does not close"
        )
    return out
