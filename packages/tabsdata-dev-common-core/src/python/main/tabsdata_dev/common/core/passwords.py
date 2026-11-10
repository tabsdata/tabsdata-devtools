#
# Copyright 2026 Tabsdata Inc.
#

"""Generated secrets for provisioned resources."""

from __future__ import annotations

import secrets
import string

# The punctuation a generated password may use: the URL-unreserved set, and
# nothing else. A password reaches a server two ways and each rules something
# out. It is interpolated into a quoted SQL literal (`IDENTIFIED BY '...'`), so
# no quote and no backslash. And it is put in a SQLAlchemy URL that only the
# managed backends percent-encode, so nothing URL-reserved (`@ : / ? # &`) and
# no `%`, which starts an escape there. These four survive both untouched.
SAFE_SYMBOLS = "-._~"


def gen_password(length: int = 24) -> str:
    """`length` chars: 4 upper + 4 lower + 4 digits + 4 symbols + remainder
    alphanumeric, so it satisfies every database's complexity rule at once.

    The symbols are what makes that true rather than nearly true: Cloud SQL
    rejects a password with no non-alphanumeric character outright
    (``INVALID_PASSWORD``), and an alphanumeric generator only ever passed
    everywhere else by luck of what was not being enforced.
    """
    upper = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    lower = "".join(secrets.choice(string.ascii_lowercase) for _ in range(4))
    digit = "".join(secrets.choice(string.digits) for _ in range(4))
    symbol = "".join(secrets.choice(SAFE_SYMBOLS) for _ in range(4))
    rest = "".join(
        secrets.choice(string.ascii_letters + string.digits)
        for _ in range(max(length - 16, 0))
    )
    return upper + lower + digit + symbol + rest
