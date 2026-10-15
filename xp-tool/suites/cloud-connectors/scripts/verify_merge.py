#
# Copyright 2026 Tabsdata Inc.
#
"""Check a warehouse merge target against the batch just applied to it.

    verify_merge.py --system bigquery|snowflake|databricks --domain DOMAIN --batch BATCH

Reads the batch's target straight from the warehouse -- not through tabsdata,
which is what is under test -- and fails unless it holds exactly the rows
``functions/_merge_plan.py`` says the batch leaves: the same keys, each once,
with the same ``name`` and ``qty``, and no ``op`` column (the marker says what
to do with a row and is never written). A target the batch should have created
and did not fails the query. Run right after the batch's non-detached ``tdk fn
trigger``, which has waited for the merge to commit.

The connection is the domain's own, from ``tdd domain info --format json``:
the same descriptor the suite's connection template reads, so the check looks
where the subscriber wrote. JSON, not ``export``: BigQuery's service-account
key is a multi-line value. The JSON is tdd's event stream; the descriptor is a
field of its ``ok`` event. Each system needs its client, which the step's
``reqs`` provide -- imported only for the system asked for.

Columns are matched without case: Snowflake folds the unquoted names the
destination created to upper case.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from tdd import TddError, note, tdd  # on the path: xp runs a python step with it

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "functions"))
import _merge_plan as plan  # noqa: E402 -- standard library only


def domain_meta(domain: str) -> dict[str, str]:
    """The domain descriptor's meta. `--format json` is tdd's event stream, one
    JSON object a line; the descriptors are fields of the run's `ok` event."""
    out = tdd("domain", "info", "--domain", domain, "--format", "json")
    for line in out.splitlines():
        event = json.loads(line) if line.startswith("{") else {}
        if event.get("event") == "ok" and event.get("descriptors"):
            return event["descriptors"][0]["meta"]
    raise TddError(("domain", "info", "--domain", domain), 0, f"no descriptor in:\n{out}")


def read_bigquery(meta: dict[str, str], target: str) -> tuple[list[str], list[tuple]]:
    from google.cloud import bigquery

    key = meta["SERVICE_ACCOUNT_KEY"]
    if key.lstrip().startswith("{"):
        client = bigquery.Client.from_service_account_info(json.loads(key), project=meta["PROJECT"])
    else:
        client = bigquery.Client.from_service_account_json(key, project=meta["PROJECT"])
    table = f"`{meta['PROJECT']}.{meta['DATASET']}.{target}`"
    result = client.query(f"SELECT * FROM {table}").result()
    return [field.name for field in result.schema], [tuple(row.values()) for row in result]


def read_snowflake(meta: dict[str, str], target: str) -> tuple[list[str], list[tuple]]:
    import snowflake.connector

    # The connection the destination opens (connections/snowflake_bulk_out.yaml),
    # and the namespace it then asserts: connect() takes database and schema as
    # login parameters only, and a session that cannot adopt them falls back to
    # the role's default without a word. The connector issues USE with an
    # identifier-shaped name unquoted, so Snowflake folds it onto the stored
    # (upper-case) schema; so does this.
    #
    # The table is another matter: the connector double-quotes every part of a
    # table name as written (_impl._fq_for_sql), so tables=["cap_merge"] is the
    # lower-case "cap_merge", not CAP_MERGE. Quoted here the same way.
    def ident(name: str) -> str:
        return name if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_$]*", name) else '"' + name.replace('"', '""') + '"'

    with snowflake.connector.connect(
        account=meta["ACCOUNT"],
        user=meta["USERNAME"],
        password=meta["PAT"],
        warehouse=meta["WAREHOUSE"],
    ) as conn:
        cursor = conn.cursor()
        cursor.execute(f"USE DATABASE {ident(meta['DATABASE'])}")
        cursor.execute(f"USE SCHEMA {ident(meta['SCHEMA'])}")
        cursor.execute(f'SELECT * FROM "{target}"')
        return [column[0] for column in cursor.description], cursor.fetchall()


def read_databricks(meta: dict[str, str], target: str) -> tuple[list[str], list[tuple]]:
    from databricks import sql

    host = meta["HOST"].replace("https://", "").replace("http://", "").rstrip("/")
    with sql.connect(
        server_hostname=host,
        http_path=f"/sql/1.0/warehouses/{meta['WAREHOUSE_ID']}",
        access_token=meta["TOKEN"],
        catalog=meta["CATALOG"],
        schema=meta["SCHEMA"],
    ) as conn, conn.cursor() as cursor:
        cursor.execute(f"SELECT * FROM {target}")
        return [column[0] for column in cursor.description], [tuple(r) for r in cursor.fetchall()]


READERS = {"bigquery": read_bigquery, "snowflake": read_snowflake, "databricks": read_databricks}


def compare(columns: list[str], rows: list[tuple], expected: plan.State) -> list[str]:
    """What is wrong with the target, one line each; empty when it is as planned."""
    folded = [column.lower() for column in columns]
    problems = []
    if plan.MARKER in folded:
        problems.append(f"the target carries the marker column {plan.MARKER!r}")
    absent = [column for column in plan.COLUMNS if column not in folded]
    if absent:
        return problems + [f"the target has no column {', '.join(absent)} (it has {', '.join(columns)})"]
    at = [folded.index(column) for column in plan.COLUMNS]
    actual: dict[int, tuple[str, int]] = {}
    for row in rows:
        key, name, qty = (row[i] for i in at)
        key = int(key) if key is not None else None
        value = (name, int(qty) if qty is not None else None)
        if key in actual:
            problems.append(f"{plan.KEY}={key} is there twice: {actual[key]} and {value}")
        actual[key] = value
    for key in sorted(set(expected) | set(actual), key=lambda k: (k is None, k or 0)):
        if key not in actual:
            problems.append(f"{plan.KEY}={key} is missing, expected {expected[key]}")
        elif key not in expected:
            problems.append(f"{plan.KEY}={key} should not be there, found {actual[key]}")
        elif actual[key] != expected[key]:
            problems.append(f"{plan.KEY}={key} is {actual[key]}, expected {expected[key]}")
    return problems


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--system", required=True, choices=sorted(READERS))
    parser.add_argument("--domain", required=True, help="the warehouse domain the merge writes to")
    parser.add_argument("--batch", required=True, choices=plan.NAMES)
    args = parser.parse_args(argv)

    b = plan.batch(args.batch)
    try:
        meta = domain_meta(args.domain)
    except TddError as e:
        print(e, file=sys.stderr)
        return 1
    try:
        columns, rows = READERS[args.system](meta, b.target)
    except Exception as e:  # the client's own error: no table, no access, ...
        print(f"{args.system} {b.target} after {b.name} ({b.what}): cannot read it: {e}", file=sys.stderr)
        note(f"{b.name}: cannot read {b.target}")
        return 1
    problems = compare(columns, rows, b.expected)
    if problems:
        print(f"{args.system} {b.target} after {b.name} ({b.what}):", file=sys.stderr)
        for problem in problems:
            print(f"  {problem}", file=sys.stderr)
        note(f"{b.name}: {len(problems)} problem(s) in {b.target}")
        return 1
    note(f"{b.name} ({b.what}): {len(rows)} row(s) in {b.target} as planned")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
