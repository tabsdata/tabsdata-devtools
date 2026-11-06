#
# Copyright 2026 Tabsdata Inc.
#
"""Set up, and check, a schema-evolution lane's tables.

    verify_evo.py --lane LANE --domain DOMAIN --setup
    verify_evo.py --lane LANE --domain DOMAIN --phase 1|2 --proj P --coll C [--profile NAME]

``--setup`` drops every table of the lane -- a run starts from nothing, however
often it runs -- and creates the ones ``_evo_plan.made_by_setup`` names, with
the seed frame's types: every seeded table on a destination that cannot create
its target, and the 32-bit ones on the SQL databases, whose writes would create
them 64-bit. ``--phase N`` reads every table from
the database itself -- not through tabsdata, which is what is under test -- and
fails unless it holds exactly the state ``functions/_evo_plan.py`` gives it after
that phase: the same columns (without case: Oracle, Db2 and Snowflake fold the
names) and the same rows. After phase 2 it also fails unless the subscriber of
every refused write failed with the refusal, read from its worker logs (``tdk
worker list``/``logs``): a table left alone because its subscriber never ran is
not a refusal.

The connection is the domain's own, from ``tdd domain info --format json`` --
the event stream's ``ok`` event carries the descriptor. A SQL system is reached
through SQLAlchemy over the descriptor's credential-bearing URI, with the driver
the step's ``reqs`` provide; a warehouse through its own client. Each is imported
only for the lane asked for.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from decimal import Decimal
from pathlib import Path

from tdd import TddError, note, tdd  # on the path: xp runs a python step with it

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))
import _evo_plan as plan  # noqa: E402 -- standard library only

#: `--profile NAME` for every tdk call, or nothing.
PROFILE: list[str] = []

#: The seed frames' types, per lane, as the setup creates a table holding them
#: (`_evo_plan.made_by_setup`): 32 bits stay 32 bits, which a write creating the
#: table would not keep on the SQL databases. Oracle's are the widening itests'.
_TYPES = {
    "starrocks": {"Int32": "INT", "Int64": "BIGINT", "String": "VARCHAR(255)"},
    "postgres": {"Int32": "INTEGER", "Int64": "BIGINT", "String": "TEXT"},
    "mysql": {"Int32": "INT", "Int64": "BIGINT", "String": "VARCHAR(255)"},
    "mssql": {"Int32": "INT", "Int64": "BIGINT", "String": "NVARCHAR(255)"},
    "oracle": {"Int32": "NUMBER(10)", "Int64": "NUMBER(19)", "String": "VARCHAR2(255)"},
    "db2": {"Int32": "INTEGER", "Int64": "BIGINT", "String": "VARCHAR(255)"},
}


def domain_meta(domain: str) -> dict[str, str]:
    out = tdd("domain", "info", "--domain", domain, "--format", "json")
    for line in out.splitlines():
        event = json.loads(line) if line.startswith("{") else {}
        if event.get("event") == "ok" and event.get("descriptors"):
            return event["descriptors"][0]["meta"]
    raise TddError(("domain", "info", "--domain", domain), 0, f"no descriptor in:\n{out}")


# ------------------------------------------------------------- databases ----


class Db:
    """A lane's database: read a table, drop one, run a statement."""

    def read(self, table: str) -> tuple[list[str], list[tuple]]:
        raise NotImplementedError

    def drop(self, table: str) -> None:
        raise NotImplementedError

    def execute(self, sql: str) -> None:
        raise NotImplementedError

    def close(self) -> None:
        pass


class SqlAlchemyDb(Db):
    # A missing table, as each database without DROP TABLE IF EXISTS says it.
    _MISSING = re.compile(r"ORA-00942|SQL0204N", re.IGNORECASE)

    def __init__(self, meta: dict[str, str]):
        from sqlalchemy import create_engine

        uri = meta.get("SQLALCHEMY_URI") or meta.get("EXTERNAL_SQLALCHEMY_URI")
        if not uri:
            raise RuntimeError("the domain descriptor has no SQLALCHEMY_URI")
        self.engine = create_engine(uri)
        # The quoting the connector's own SQLAlchemy writes with: a lower-case
        # name goes unquoted, so Oracle and Db2 fold it as they folded the table.
        self.quote = self.engine.dialect.identifier_preparer.quote
        self.if_exists = self.engine.dialect.name not in ("oracle", "ibm_db_sa")

    def read(self, table):
        from sqlalchemy import text

        with self.engine.connect() as conn:
            result = conn.execute(text(f"SELECT * FROM {self.quote(table)}"))
            return list(result.keys()), [tuple(row) for row in result]

    def drop(self, table):
        if self.if_exists:
            self.execute(f"DROP TABLE IF EXISTS {self.quote(table)}")
            return
        try:
            self.execute(f"DROP TABLE {self.quote(table)}")
        except Exception as e:  # the driver's own
            if not self._MISSING.search(str(e)):
                raise

    def execute(self, sql):
        from sqlalchemy import text

        with self.engine.begin() as conn:
            conn.execute(text(sql))

    def close(self):
        self.engine.dispose()


class BigQueryDb(Db):
    def __init__(self, meta):
        from google.cloud import bigquery

        key = meta["SERVICE_ACCOUNT_KEY"]
        if key.lstrip().startswith("{"):
            self.client = bigquery.Client.from_service_account_info(json.loads(key), project=meta["PROJECT"])
        else:
            self.client = bigquery.Client.from_service_account_json(key, project=meta["PROJECT"])
        self.prefix = f"{meta['PROJECT']}.{meta['DATASET']}"

    def read(self, table):
        result = self.client.query(f"SELECT * FROM `{self.prefix}.{table}`").result()
        return [field.name for field in result.schema], [tuple(row.values()) for row in result]

    def drop(self, table):
        self.execute(f"DROP TABLE IF EXISTS `{self.prefix}.{table}`")

    def execute(self, sql):
        self.client.query(sql).result()


class SnowflakeDb(Db):
    """The connector double-quotes a table name as written, so the tables are the
    lower-case ``"evo_..."``; database and schema are set as it sets them."""

    def __init__(self, meta):
        import snowflake.connector

        def ident(name: str) -> str:
            return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) else '"' + name.replace('"', '""') + '"'

        self.conn = snowflake.connector.connect(
            account=meta["ACCOUNT"], user=meta["USERNAME"], password=meta["PAT"], warehouse=meta["WAREHOUSE"]
        )
        self.cursor = self.conn.cursor()
        self.cursor.execute(f"USE DATABASE {ident(meta['DATABASE'])}")
        self.cursor.execute(f"USE SCHEMA {ident(meta['SCHEMA'])}")

    def read(self, table):
        self.cursor.execute(f'SELECT * FROM "{table}"')
        return [column[0] for column in self.cursor.description], self.cursor.fetchall()

    def drop(self, table):
        self.execute(f'DROP TABLE IF EXISTS "{table}"')

    def execute(self, sql):
        self.cursor.execute(sql)

    def close(self):
        self.conn.close()


class DatabricksDb(Db):
    def __init__(self, meta):
        from databricks import sql

        host = meta["HOST"].replace("https://", "").replace("http://", "").rstrip("/")
        self.conn = sql.connect(
            server_hostname=host,
            http_path=f"/sql/1.0/warehouses/{meta['WAREHOUSE_ID']}",
            access_token=meta["TOKEN"],
            catalog=meta["CATALOG"],
            schema=meta["SCHEMA"],
        )

    def read(self, table):
        with self.conn.cursor() as cursor:
            cursor.execute(f"SELECT * FROM {table}")
            return [column[0] for column in cursor.description], [tuple(r) for r in cursor.fetchall()]

    def drop(self, table):
        self.execute(f"DROP TABLE IF EXISTS {table}")

    def execute(self, sql):
        with self.conn.cursor() as cursor:
            cursor.execute(sql)

    def close(self):
        self.conn.close()


WAREHOUSES = {"bigquery": BigQueryDb, "snowflake": SnowflakeDb, "databricks": DatabricksDb}


def open_db(lane: str, meta: dict[str, str]) -> Db:
    return WAREHOUSES.get(lane, SqlAlchemyDb)(meta)


# ----------------------------------------------------------------- setup ----


def setup(lane: str, db: Db) -> int:
    made = 0
    for c, _, table in plan.tables(lane):
        db.drop(table)
        if plan.made_by_setup(lane, c):
            columns = plan.FRAMES[c.seed.publisher].columns
            types = _TYPES[lane]
            spec = ", ".join(f"{db.quote(n)} {types[k]}" for n, k in columns)
            db.execute(f"CREATE TABLE {db.quote(table)} ({spec})")
            made += 1
    note(f"{len(plan.tables(lane))} table(s) dropped" + (f", {made} created" if made else ""))
    return 0


# ----------------------------------------------------------------- check ----


def _value(v):
    """A value as the plan spells it: an integral number an int, whatever type
    the driver read it as (Oracle's NUMBER, Snowflake's NUMBER(38,0), ...)."""
    if isinstance(v, bool) or v is None:
        return v
    if isinstance(v, (int, float, Decimal)) and v == int(v):
        return int(v)
    return v


def state_of(columns: list[str], rows: list[tuple], expected: plan.State) -> plan.State:
    """The table as a State over `expected`'s columns when it has exactly those
    (in any case or order), else over its own."""
    folded = [c.lower() for c in columns]
    if sorted(folded) != sorted(expected.columns):
        return plan.State(tuple(sorted(folded)), ())
    at = [folded.index(c) for c in expected.columns]
    found = sorted((tuple(_value(row[i]) for i in at) for row in rows), key=repr)
    return plan.State(expected.columns, tuple(found))


def _say(state: plan.State) -> str:
    return f"columns {', '.join(state.columns)}; rows {list(state.rows)}"


def check_tables(lane: str, db: Db, phase: int) -> list[str]:
    problems = []
    for c, engine, table in plan.tables(lane):
        accepted = (c.seeded,) if phase == 1 else c.final
        try:
            columns, rows = db.read(table)
        except Exception as e:  # the client's own: no table, no access, ...
            problems.append(f"{table} ({c.what}): cannot read it: {e}")
            continue
        found = [state_of(columns, rows, s) for s in accepted]
        if not any(f.columns == s.columns and f.rows == tuple(sorted(s.rows, key=repr))
                   for f, s in zip(found, accepted)):
            wanted = " or ".join(_say(s) for s in accepted)
            problems.append(f"{table} ({c.what}): has {_say(found[0])}, expected {wanted}")
    return problems


#: `tdk worker list` statuses (`status`): a run that ended well, or failed.
DONE, FAILED = "D", "F"


def workers(proj: str, coll: str, fn: str) -> list[dict]:
    """The function's workers, as `tdk worker list --format json` lists them: one
    dict each, with its `id`, `status` (DONE, FAILED, ...) and `final`."""
    out = tdd("tdk", "worker", "list", "--proj", proj, "--coll", coll, "--fn", fn,
              "--format", "json", *PROFILE)
    return json.loads(out or "[]") or []


def worker_logs(found: list[dict]) -> list[str]:
    return [tdd("tdk", "worker", "logs", "--worker", str(w["id"]), *PROFILE, check=False)
            for w in found]


def _status(found: list[dict]) -> str:
    return ", ".join(f"{w['id']} {w.get('status_name') or w.get('status')}" for w in found)


def check_runs(lane: str, proj: str, coll: str) -> list[str]:
    """The phase-2 writes that may fail: every one ran to the end, and a refused
    one failed with the refusal."""
    problems = []
    for c, engine, table in plan.tables(lane):
        if not plan.may_fail(c):
            continue
        fn = plan.subscriber(c, 2, engine)
        found = workers(proj, coll, fn)
        if not found or not all(w.get("final") for w in found):
            problems.append(f"{fn} ({c.what}): did not run to the end -- {_status(found) or 'no worker'}")
        elif c.refused and not any(w.get("status") == FAILED for w in found):
            problems.append(f"{fn} ({c.what}): was not refused -- {_status(found)}")
        elif c.refused:
            logs = worker_logs(found)
            if not any(plan.REFUSAL_CODE in log or plan.REFUSAL_TEXT in log for log in logs):
                problems.append(
                    f"{fn} ({c.what}): failed, but no worker log carries {plan.REFUSAL_CODE}; "
                    f"it says: {_error_of(logs)}"
                )
    return problems


def _error_of(logs: list[str]) -> str:
    """The error a failed worker's log ends on: its last `Error [...]` line, or
    the last exception line -- what the refusal was instead."""
    lines = [ln.strip() for log in logs for ln in log.splitlines()]
    for marks in (("Error [",), ("Exception:", "Error:")):
        found = [ln for ln in lines if any(m in ln for m in marks)]
        if found:
            return found[-1][:600]
    return "nothing recognisable"


def trigger(lane: str, publisher: str, proj: str, source: str, coll: str) -> int:
    """Trigger a phase-2 publisher whose writes may fail, and wait for it.

    tdk's non-detached trigger exits non-zero when any run of the plan failed,
    which is the point here, so its exit is not the verdict: every subscriber the
    publisher feeds must have run to the end, and only one whose write may fail
    may have failed. Whether a refused one failed for the right reason is phase
    2's check."""
    tdd("tdk", "fn", "trigger", "--proj", proj, "--coll", source, "--name", publisher,
        *PROFILE, check=False)
    fed = [(c, plan.subscriber(c, 2, e)) for c, e, _ in plan.tables(lane)
           if c.write and c.write.publisher == publisher]
    problems, failed = [], 0
    for c, fn in fed:
        found = workers(proj, coll, fn)
        if not found or not all(w.get("final") for w in found):
            problems.append(f"{fn}: did not run to the end -- {_status(found) or 'no worker'}")
        elif any(w.get("status") == FAILED for w in found):
            failed += 1
            if not plan.may_fail(c):
                problems.append(f"{fn} ({c.what}): failed -- {_status(found)}")
    if problems or not fed:
        print(f"trigger {publisher}:", file=sys.stderr)
        for problem in problems or [f"no subscriber of {lane} reads {publisher}"]:
            print(f"  {problem}", file=sys.stderr)
        note(f"{publisher}: {len(problems)} problem(s)")
        return 1
    note(f"{publisher}: {len(fed)} subscriber(s) ran, {failed} failed")
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--lane", required=True, choices=sorted(plan.DESTINATIONS))
    parser.add_argument("--domain", required=True, help="the destination's domain")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--setup", action="store_true", help="drop (and create) the lane's tables")
    what.add_argument("--phase", type=int, choices=(1, 2), help="check the tables after this phase")
    what.add_argument("--trigger", metavar="PUBLISHER", help="trigger a phase-2 publisher whose writes may fail")
    parser.add_argument("--proj", help="the run's project (phase 2 and --trigger)")
    parser.add_argument("--source", help="the publishers' collection (--trigger)")
    parser.add_argument("--coll", help="the subscribers' collection (phase 2 and --trigger)")
    parser.add_argument("--profile", default="", help="tdk's --profile; empty: its default connection")
    args = parser.parse_args(argv)
    if args.profile:
        PROFILE[:] = ["--profile", args.profile]
    if (args.trigger or args.phase == 2) and not (args.proj and args.coll):
        parser.error("--phase 2 and --trigger take --proj and --coll")
    if args.trigger:
        if not args.source:
            parser.error("--trigger takes --source")
        return trigger(args.lane, args.trigger, args.proj, args.source, args.coll)

    try:
        db = open_db(args.lane, domain_meta(args.domain))
    except Exception as e:
        print(f"{args.lane}: cannot reach {args.domain}: {e}", file=sys.stderr)
        return 1
    try:
        if args.setup:
            return setup(args.lane, db)
        problems = check_tables(args.lane, db, args.phase)
        if args.phase == 2:
            problems += check_runs(args.lane, args.proj, args.coll)
    finally:
        db.close()
    count = len(plan.tables(args.lane))
    if problems:
        print(f"{args.lane} after phase {args.phase}:", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        note(f"phase {args.phase}: {len(problems)} problem(s) in {count} table(s)")
        return 1
    note(f"phase {args.phase}: {count} table(s) as planned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
