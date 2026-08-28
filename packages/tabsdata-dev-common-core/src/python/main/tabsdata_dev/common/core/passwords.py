#
# Copyright 2026 Tabsdata Inc.
#

"""Generated secrets for provisioned resources."""

from __future__ import annotations

import secrets
import string


def gen_password(length: int = 24) -> str:
    """`length` chars: 4 upper + 4 lower + 4 digits + remainder alphanumeric, so
    it satisfies every database's complexity rule at once."""
    upper = "".join(secrets.choice(string.ascii_uppercase) for _ in range(4))
    lower = "".join(secrets.choice(string.ascii_lowercase) for _ in range(4))
    digit = "".join(secrets.choice(string.digits) for _ in range(4))
    rest = "".join(
        secrets.choice(string.ascii_letters + string.digits)
        for _ in range(max(length - 12, 0))
    )
    return upper + lower + digit + rest
