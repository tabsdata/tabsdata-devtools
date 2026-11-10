#
# Copyright 2026 Tabsdata Inc.
#

"""What the database itself said about a failure, for the log.

The one line a command prints is the driver's summary -- "permission denied for
schema public". The server knew more: the SQLSTATE, which schema and table, the
DETAIL and HINT it wrote for exactly this case, the statement that provoked it.
None of that reaches the terminal, and without it a failure often needs a second
run by hand to diagnose. :func:`db_failure` collects it into the block
``ToolError(details=...)`` writes to the log under the error line.

Collection never raises. A diagnostic that blows up while explaining a failure
would replace the failure, which is strictly worse than not having it.
"""

from __future__ import annotations

import re
import textwrap

#: psycopg2 exposes these on `exc.diag`; the names are libpq's own
#: (PG_DIAG_MESSAGE_DETAIL and friends). Ordered as a reader wants them, and
#: `source_file`/`source_line`/`source_function` are left out on purpose: they
#: point into the *server's* C source, which tells a user nothing.
_PG_DIAG = (
    ("severity", "severity"),
    ("message_primary", "message"),
    ("message_detail", "detail"),
    ("message_hint", "hint"),
    ("context", "context"),
    ("schema_name", "schema"),
    ("table_name", "table"),
    ("column_name", "column"),
    ("constraint_name", "constraint"),
    ("datatype_name", "datatype"),
    ("internal_query", "internal query"),
    ("statement_position", "position"),
)

#: Where the SQLSTATE (or the driver's equivalent) hides, by driver: psycopg2
#: `pgcode`, oracledb `code`; pymysql has none, only the error number first in
#: its args.
_CODE_ATTRS = ("pgcode", "sqlstate", "errno", "code")


def redact_url(url: str) -> str:
    """A connection URL with the password removed -- the target belongs in the
    log, the credential does not."""
    try:
        from sqlalchemy.engine import make_url

        return make_url(url).render_as_string(hide_password=True)
    except Exception:  # noqa: BLE001 -- any parse failure falls back to the regex
        return re.sub(r"(://[^:/@]+:)[^@]*@", r"\1***@", url)


def _row(lines: list[str], label: str, value: object) -> None:
    text = "" if value is None else str(value).strip()
    if text:
        lines.append(f"{label}: {text}" if "\n" not in text else f"{label}:")
        if "\n" in text:
            lines.append(textwrap.indent(text, "  "))


def db_failure(
    exc: BaseException, *, statement: str = "", url: str = "", label: str = ""
) -> str:
    """The block that goes under a database failure in the log: the driver's own
    exception, its SQLSTATE, every diagnostic field the server sent, the failing
    statement and the connection target with the password stripped.

    `exc` is the SQLAlchemy error (its `.orig` is unwrapped) or the DBAPI one
    directly. `statement` is what we were running when it is not already on the
    exception.
    """
    lines: list[str] = []
    try:
        if label:
            _row(lines, "while", label)
        orig = getattr(exc, "orig", None) or exc
        _row(lines, "driver error", f"{type(orig).__name__}: {orig}")
        for attr in _CODE_ATTRS:
            code = getattr(orig, attr, None)
            # oracledb hangs `code` off the args, and a callable is not a code
            if code and not callable(code):
                _row(
                    lines, "sqlstate" if attr in ("pgcode", "sqlstate") else attr, code
                )
                break
        else:
            args = getattr(orig, "args", ())
            if args and isinstance(args[0], int):
                _row(lines, "errno", args[0])
        diag = getattr(orig, "diag", None)
        for attr, name in _PG_DIAG:
            _row(lines, name, getattr(diag, attr, None) if diag else None)
        stmt = statement or getattr(exc, "statement", "") or ""
        _row(lines, "statement", stmt)
        _row(lines, "connection", redact_url(url) if url else "")
    except Exception as collecting:  # noqa: BLE001 -- see the module docstring
        lines.append(f"(diagnostics unavailable: {collecting})")
    return "\n".join(lines)
