#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the schema-evolution suites: one lane per table destination, each held
to the whole ``schema_evolution`` policy (``functions/_evo_plan.py`` says what and
why).

    python suites/schema-evolution/gen_suites.py

Writes ``<lane>.json`` and ``functions/evo_<lane>.py`` -- the lane's subscribers,
two per case: ``<table>_seed`` writes phase 1, ``<table>_write``
phase 2, each decorator spelling its destination out. A lane runs:

1. ``setup`` (``scripts/verify_evo.py --setup``) drops every table of the lane, so
   a run starts from nothing however often it runs, and creates the tables
   ``_evo_plan.made_by_setup`` names with the seed frame's types: every seeded
   one on a destination that cannot create its target (StarRocks), and the
   32-bit ones on the SQL databases, whose writes would make them 64-bit; their
   seeds then append.
2. Phase 1's publishers, each a non-detached ``tdk fn trigger``, and the check.
3. Phase 2's publishers -- the writes that must succeed, then the ones that may
   fail -- and the check, which also reads a refused write's worker log. tdk's
   non-detached trigger exits non-zero when a run of its plan failed, so a
   publisher whose writes may fail is triggered by ``verify_evo.py --trigger``,
   which judges the subscribers' workers instead: each ran to the end, and only
   one whose write may fail failed.

There is no monitor stage: refused writes fail their transactions on purpose,
and a monitor fails a run that holds one. The checks decide.

Change the cases in ``_evo_plan.py`` or a destination here and re-run; never edit
the generated files by hand.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
FUNCTIONS = SUITE / "functions"
sys.path.insert(0, str(FUNCTIONS))
import _evo_plan as plan  # noqa: E402 -- standard library only

COPYRIGHT = "#\n# Copyright 2026 Tabsdata Inc.\n#\n"
SCRIPT = "scripts/verify_evo.py"
INPUT = "evo_input"
OUTPUT = "evo_out"
SQLALCHEMY = "sqlalchemy==2.0.55"

# lane -> how the suite reaches it: the connector, the system and connection the
# capability suites use for it, a staging store when it loads through one, and
# what the check needs to read it (the drivers tdd's systems toolset pins, and the
# warehouse clients the merge checks use).
LANES = {
    "postgres": dict(
        module="tabsdatak.conn.postgres", dest="PostgresDest", system="postgres",
        conn="postgres_sql_out", reqs=[SQLALCHEMY, "psycopg2-binary==2.9.13"],
    ),
    "mysql": dict(
        module="tabsdatak.conn.mysql", dest="MySQLDest", system="mysql",
        conn="mysql_sql_out", reqs=[SQLALCHEMY, "pymysql==1.2.3"],
    ),
    "mssql": dict(
        module="tabsdatak.conn.mssql", dest="MSSQLDest", system="mssqlserver",
        conn="mssql_sql_out", reqs=[SQLALCHEMY, "pyodbc==5.3.0"],
    ),
    "oracle": dict(
        module="tabsdatak.conn.oracle", dest="OracleDest", system="oracle",
        conn="oracle_sql_out", reqs=[SQLALCHEMY, "oracledb==26.1.0"],
    ),
    "db2": dict(
        module="tabsdatak.conn.db2", dest="Db2Dest", system="db2",
        conn="db2_sql_out", reqs=[SQLALCHEMY, "ibm_db==3.3.0", "ibm_db_sa==0.4.4"],
    ),
    # Azure staging: azureBlobStorage() needs no extra grant, where the s3/gcs
    # variants need `GRANT CREATE TEMPORARY TABLE, S3` on the user (clickhouse.json).
    "clickhouse": dict(
        module="tabsdatak.conn.clickhouse", dest="ClickHouseDest", system="clickhouse",
        conn="clickhouse_bulk_out_az", staging="azureblob",
        reqs=[SQLALCHEMY, "clickhouse-connect==1.11.0"],
    ),
    "starrocks": dict(
        module="tabsdatak.conn.starrocks", dest="StarRocksDest", system="starrocks",
        conn="starrocks_bulk_out_s3", staging="s3",
        reqs=[SQLALCHEMY, "pymysql==1.2.3"],
    ),
    "databricks": dict(
        module="tabsdatak.conn.databricks", dest="DatabricksDest", system="databricks",
        conn="databricks_bulk_out", reqs=["databricks-sql-connector==4.5.0"],
    ),
    "snowflake": dict(
        module="tabsdatak.conn.snowflake", dest="SnowflakeDest", system="snowflake",
        conn="snowflake_bulk_out", reqs=["snowflake-connector-python==4.7.3"],
    ),
    # BigQuery wraps the whole name in one backtick pair; the connection completes
    # project and dataset.
    "bigquery": dict(
        module="tabsdatak.conn.bigquery", dest="BigQueryDest", system="bigquery",
        conn="bigquery_bulk_out", quote="`", reqs=["google-cloud-bigquery==3.44.0"],
    ),
}


def _destination(lane: str, c: plan.Case, w: plan.Write) -> str:
    spec = LANES[lane]
    q = spec.get("quote", "")
    engine = plan.engine(lane, w)
    args = [
        f'tables=["{q}{plan.table(c)}{q}"]',
        f'if_table_exists="{w.mode}"',
        f'schema_evolution="{w.evolution}"',
    ]
    if w.mode == plan.MERGE:
        args.append(f'merge_cfg=[MergeCfg(on=["{plan.MERGE_KEY}"], op_column="{plan.MERGE_OP}")]')
    if engine:
        args.append(f'dest_cfg={{"{lane}.schema_evolution_engine": "{engine}"}}')
    inner = ",\n        ".join(args)
    return f"{spec['dest']}(\n        {inner},\n    )"


def functions_module(lane: str) -> str:
    spec = LANES[lane]
    d = plan.DESTINATIONS[lane]
    imports = spec["dest"] + (", MergeCfg" if d.merge else "")
    head = COPYRIGHT + f'''
"""evo_{lane} -- GENERATED by gen_suites.py from _evo_plan.py; do not edit.

The {spec["dest"]} subscribers of the schema-evolution lane: per case
``<table>_seed``, phase 1, and ``<table>_write``, phase 2, each reading the
``{INPUT}`` publisher of the frame it writes.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, subscriber
from {spec["module"]} import {imports}
'''
    parts = [head]
    for c, _ in plan.tables(lane):
        for phase, w in ((1, plan.seed(lane, c)), (2, c.write)):
            if w is None:
                continue
            name = plan.subscriber(c, phase)
            parts.append(f'''

# {c.name}, phase {phase}: {c.what}.
@subscriber(
    destination={_destination(lane, c, w)},
    input_tables=["{INPUT}/{w.publisher}"],
)
def {name}(rows: TableFrameSpec) -> TableFrameSpec:
    return rows
''')
    return "".join(parts)


def _check(lane: str, name: str, *args: str) -> dict:
    spec = LANES[lane]
    params = ["--lane", lane, "--domain", f"${{xp:name({lane})}}", *args,
              "--proj", "${xp:project}", "--coll", OUTPUT, "--profile", "${td:profile}"]
    return {"python": {"name": name, "tags": ["check"], "script": SCRIPT,
                       "params": params, "reqs": spec["reqs"]}}


def _trigger(lane: str, publisher: str, phase: int) -> dict:
    d = plan.DESTINATIONS[lane]
    if phase == 2 and any(plan.may_fail(c) for c in plan.cases(d.merge)
                          if c.write and c.write.publisher == publisher):
        # tdk's trigger exits non-zero when a run of the plan failed, which is
        # what this one may do: the script triggers and judges by the workers.
        check = _check(lane, f"p{phase}-{publisher}", "--trigger", publisher, "--source", INPUT)
        check["python"]["tags"] = [f"phase{phase}"]
        return check
    return {"tdd": {
        "name": f"p{phase}-{publisher}",
        "tags": [f"phase{phase}"],
        "tool": "tdk",
        "command": "fn",
        "options": ["trigger", "--proj", "${xp:project}", "--coll", INPUT,
                    "--name", publisher, "--profile", "${td:profile}"],
    }}


def suite(lane: str) -> list:
    spec = LANES[lane]
    d = plan.DESTINATIONS[lane]
    phase1, phase2 = plan.publishers(1, d.merge), plan.publishers(2, d.merge)
    domains = [{"name": "${xp:name(dev)}", "system": "dev"},
               {"name": f"${{xp:name({lane})}}", "system": spec["system"]}]
    dmap = {"D0": f"${{xp:name({lane})}}"}
    if spec.get("staging"):
        domains.append({"name": f"${{xp:name({spec['staging']})}}", "system": spec["staging"]})
        dmap["D1"] = f"${{xp:name({spec['staging']})}}"
    names = [c.name for c in plan.cases(d.merge)]
    comment = (
        f"SCHEMA EVOLUTION, {spec['dest']} (GENERATED by gen_suites.py; do not edit): the "
        f"schema_evolution policy end to end, the cases of tabsdata-os' shared schema policy "
        f"itests -- {', '.join(names)}. Every case owns a table "
        f"(evo_<case>) and is written in two phases from "
        f"the dev publishers of functions/evo_frames.py: phase 1 seeds every table, phase 2 "
        f"writes the frame under test (the writes that must succeed first, then the ones "
        f"that may fail, triggered by verify_evo.py --trigger, which accepts tdk's failed "
        f"exit and judges by the workers), each publisher a non-detached trigger; after each phase "
        f"scripts/verify_evo.py reads every table from {spec['system']} itself and fails "
        f"unless it holds exactly the plan's state, and after phase 2 also unless every "
        f"refused write's worker log carries the refusal ({plan.REFUSAL_CODE}). "
        + (f"No write names an engine but the update merges, which have to name "
           f"{d.merge_update_engine}: the native evolution does not apply to MERGE. "
           if d.merge_update_engine else "")
        + ("StarRocks cannot create its target, so the setup step creates each seeded "
           "table with the seed's types. " if not d.creates else "")
        + ("A write creates a 32-bit column 64-bit here, so the setup step creates the "
           "narrow tables (score 32-bit) and their seeds append into them, as the widening "
           "itests do. " if d.narrow_ddl else "")
        + "No monitor stage: refused writes fail their transactions on purpose. "
        f"Run: `tdd xp one-shot --suite schema-evolution/{lane}`."
    )
    functions = [
        {"collection": INPUT, "functionpath": f"functions/evo_frames.py::{p}"}
        for p in phase1 + phase2
    ] + [
        {"collection": OUTPUT, "functionpath": f"functions/evo_{lane}.py::{plan.subscriber(c, phase)}"}
        for c, _ in plan.tables(lane)
        for phase, w in ((1, plan.seed(lane, c)), (2, c.write))
        if w is not None
    ]
    actions = (
        [_check(lane, "setup", "--setup")]
        + [_trigger(lane, p, 1) for p in phase1]
        + [_check(lane, "check-phase1", "--phase", "1")]
        + [_trigger(lane, p, 2) for p in phase2]
        + [_check(lane, "check-phase2", "--phase", "2")]
    )
    return [
        {"_comment": comment},
        {"domain-manifest": {"domains": domains}},
        {"collections": [
            {"name": INPUT, "type": "datagen_in",
             "connection_template": "connection-file:connections/datagen_in.yaml",
             "group": "sources", "domains": {"D0": "${xp:name(dev)}"}},
            {"name": OUTPUT, "type": spec["conn"],
             "connection_template": f"connection-file:connections/{spec['conn']}.yaml",
             "group": "destinations", "domains": dmap},
        ]},
        {"functions": functions},
        {"actions": actions},
    ]


def main() -> int:
    assert set(LANES) == set(plan.DESTINATIONS), "a lane without its destination, or the reverse"
    for lane in LANES:
        (SUITE / f"{lane}.json").write_text(
            json.dumps(suite(lane), indent=2) + "\n", encoding="utf-8"
        )
        (FUNCTIONS / f"evo_{lane}.py").write_text(functions_module(lane), encoding="utf-8")
    print(f"wrote {len(LANES)} lane(s) under {SUITE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
