#
# Copyright 2026 Tabsdata Inc.
#

"""Execute SQL via SQLAlchemy — inline text or one-transaction-per-list.

``run_sql_text`` runs a whole script in one transaction (commit at end).
``run_sql_transactions`` runs each inner list as its own transaction (one commit
each), preserving the per-transaction boundaries a change-data-capture consumer
sees as distinct transactions. ``run_sql_schedule`` runs them as a ``trx``
schedule says -- several open at once on connections of their own, their
statements interleaved and their commits in the schedule's order. DBAPI / SQLAlchemy errors are converted to
``TdxError`` so the top-level handler prints the database's own message instead
of a Python traceback -- carrying the server's full diagnostics (SQLSTATE,
DETAIL, HINT, the failing statement) as the log's detail block, since the one
line on the terminal is rarely enough to tell what to change.
"""

from __future__ import annotations

import contextlib
import re

from tabsdata_dev.common.systems.diagnostics import db_failure
from tabsdata_dev.common.systems.errors import TdxError

_SQL_COMMENT_RE = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)


# The drivers that format a statement with `%` even when it has no parameters,
# as SQLAlchemy runs every statement as written: a literal `%` must be doubled.
# mysql-connector and pg8000 leave such a statement alone.
_PERCENT_FORMATTING_DRIVERS = frozenset(
    {"pymysql", "mysqldb", "psycopg2", "psycopg2cffi"}
)


def as_written(conn, statement: str):
    """Run ``statement`` exactly as written -- its `%` included -- on a
    SQLAlchemy connection, returning the result."""
    if conn.dialect.driver in _PERCENT_FORMATTING_DRIVERS:
        statement = statement.replace("%", "%%")
    return conn.exec_driver_sql(statement)


def _is_only_comments(fragment: str) -> bool:
    return not _SQL_COMMENT_RE.sub("", fragment).strip()


def split_sql_statements(sql: str) -> list[str]:
    """Split a SQL script into statements — sqlparse if available, else a naive
    `;` split. Comment-only / empty fragments are dropped; a trailing `;` is
    stripped from each."""
    try:
        import sqlparse

        parts = sqlparse.split(sql)
    except ImportError:
        no_comments = "\n".join(
            ln for ln in sql.splitlines() if not ln.lstrip().startswith("--")
        )
        parts = no_comments.split(";")
    out: list[str] = []
    for st in parts:
        st = st.strip().rstrip(";").strip()
        if st and not _is_only_comments(st):
            out.append(st)
    return out


def run_sql_text(uri: str, sql: str, label: str = "sql") -> None:
    """Execute the given SQL text in a single transaction."""
    if not uri:
        raise TdxError("SQLALCHEMY_URI is empty")

    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError

    statements = split_sql_statements(sql)
    engine = create_engine(uri)
    running = ""
    try:
        with engine.begin() as conn:
            for stmt in statements:
                stmt = stmt.rstrip(";").strip()
                if stmt:
                    running = stmt
                    as_written(conn, stmt)
    except SQLAlchemyError as exc:
        orig = getattr(exc, "orig", None) or exc
        raise TdxError(
            f"SQL error while running {label}: {orig}",
            db_failure(exc, statement=running, url=uri, label=label),
        ) from None
    finally:
        # Dispose the pool so no connection lingers to block a later DROP DATABASE.
        engine.dispose()


def run_sql_transactions(
    uri: str, transactions: list[list[str]], label: str = "changes"
) -> int:
    """Run each inner list of statements as ONE transaction (a single commit),
    returning the number of transactions applied. All share one engine/pool."""
    if not uri:
        raise TdxError("SQLALCHEMY_URI is empty")

    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError

    engine = create_engine(uri)
    applied = 0
    running = ""
    try:
        for stmts in transactions:
            with engine.begin() as conn:
                for stmt in stmts:
                    stmt = stmt.rstrip(";").strip()
                    if stmt:
                        running = stmt
                        as_written(conn, stmt)
            applied += 1
    except SQLAlchemyError as exc:
        orig = getattr(exc, "orig", None) or exc
        raise TdxError(
            f"SQL error while running {label}: {orig}",
            db_failure(
                exc,
                statement=running,
                url=uri,
                label=f"{label}, transaction {applied + 1}",
            ),
        ) from None
    finally:
        engine.dispose()
    return applied


def run_sql_schedule(
    uri: str,
    transactions: list[list[str]],
    steps: list,
    *,
    setup: list[str],
    label: str = "changes",
) -> int:
    """Run `transactions` as `steps` (``trx.Step``) say: a BEGIN opens a
    connection of its own and runs `setup` on it, a STATEMENT runs that
    transaction's next statement there, a COMMIT commits it and closes the
    connection. One thread moves through the steps, so the statements interleave
    exactly as scheduled -- and a statement that waits on a lock another open
    transaction holds waits here, for a commit that cannot come until it
    returns; the dialect's lock timeout in `setup` is what turns that into an
    error. Every step goes to the detail log. A failure rolls back whatever is
    still open. Returns the number of transactions committed."""
    if not uri:
        raise TdxError("SQLALCHEMY_URI is empty")

    from sqlalchemy import create_engine
    from sqlalchemy.exc import SQLAlchemyError
    from sqlalchemy.pool import NullPool
    from tabsdata_dev.common.systems.trx import Action

    # No pool: a connection per open transaction, as many as the schedule
    # opens at once, each closed at its commit.
    engine = create_engine(uri, poolclass=NullPool)
    open_: dict[int, tuple] = {}
    applied = 0
    running = ""
    current = -1
    try:
        for step in steps:
            current = step.txn
            if step.action is Action.BEGIN:
                conn = engine.connect()
                txn = conn.begin()
                open_[step.txn] = (conn, txn)
                print(f">>> txn {step.txn}: begin")
                for stmt in setup:
                    running = stmt
                    as_written(conn, stmt)
            elif step.action is Action.STATEMENT:
                conn, _ = open_[step.txn]
                stmt = transactions[step.txn][step.index].rstrip(";").strip()
                if stmt:
                    running = stmt
                    print(f">>> txn {step.txn}: {stmt}")
                    as_written(conn, stmt)
            else:
                conn, txn = open_.pop(step.txn)
                txn.commit()
                conn.close()
                applied += 1
                print(f">>> txn {step.txn}: commit")
    except SQLAlchemyError as exc:
        orig = getattr(exc, "orig", None) or exc
        raise TdxError(
            f"SQL error while running {label}: {orig}",
            db_failure(
                exc,
                statement=running,
                url=uri,
                label=f"{label}, transaction {current} ({len(open_)} open)",
            ),
        ) from None
    finally:
        for conn, txn in open_.values():
            with contextlib.suppress(
                Exception
            ):  # already failing; the first error wins
                txn.rollback()
                conn.close()
        engine.dispose()
    return applied
