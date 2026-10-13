#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the performance suite JSONs: two per CDC source, one for Kafka JSON.

    python suites/performance/gen_suites.py

What they measure is INGESTION, before a trigger hands the files over as a
manifest (the trigger's and the commit's time is latency the thresholds
choose), as two figures: READ, the rows the source yielded over the seconds the
plugin waited on it for them -- the source's own speed; and END TO END, the
rows a stream publisher writes to its files over the time from its run() to
the last file. ``scripts/cdc_throughput.py`` reads both off the stream worker's
log and says them in the step's note.

Every suite runs over one domain of the ``employeescdc`` model loaded with
``create-data --size SIZE`` -- ``BASE_SIZE`` (100) x SIZE rows in each of its four
tables, a million rows in all at 2500 -- BEFORE the stream is registered, so the
stream reads a backlog as fast as it can instead of keeping pace with an insert:

- ``<source>_initial_load``: registered with ``start_from="full"`` -- its snapshot
  is the whole million.
- ``<source>_changes``: registered from the head -- the million are changes in the
  source's log (the WAL through the domain's slot, the binlog, the CD tables),
  read from the start.

A stream that has not written everything ``TIME_OUT`` after it is measured is
reported as PARTIAL -- rows written, rows expected, rate -- and the step still
passes: these suites measure, they do not judge. Change SIZE or TIME_OUT here
and re-run; never edit the JSONs by hand.

``kafka_json`` measures the Kafka stream source the same way, with the same
script: the stream ledger it reads is shared by every stream source. Its
backlog is the redpanda domain's own data plane: ``KAFKA_PASSES`` passes of
``modify-data --entity employees --size KAFKA_SIZE``, ``BASE_SIZE`` x
KAFKA_SIZE messages each, before the publisher is registered. In passes, not
one ``create-data`` of the whole: the model's generator builds every table of
the employees model for a load, some twelve rows for each employee sent (at a
million, ~3.5 GB at its peak); a pass of 250k is ~0.9 GB. Ten million, because
the source reads a backlog at around a million rows a second: a million is
gone in about a second, most of it the stream's start.
"""

from __future__ import annotations

import json
from pathlib import Path

SUITE = Path(__file__).resolve().parent
MODEL = "employeescdc"
TABLES = ["accounts", "ledger", "devices", "readings"]
BASE_SIZE = 100  # rows a table per --size unit (common.systems.datagen.BASE_SIZE)
SIZE = 2500
TIME_OUT = "10m"
# A changes lane waits this long after the load before it registers the
# publisher: the source has then captured the load in full (Db2 Capture into
# the CD tables, the WAL, the binlog) and the measured window, which starts at
# the plugin's run(), holds the read alone rather than the capture lag.
SETTLE = "60s"
SCRIPT = "scripts/cdc_throughput.py"
KAFKA_SIZE = 2500
KAFKA_PASSES = 40
KAFKA_ROWS = BASE_SIZE * KAFKA_SIZE * KAFKA_PASSES

# source -> (system, collection type, connection per suite kind, the log it reads)
SOURCES = {
    "postgrescdc": (
        "postgrescdc",
        "postgres_cdc",
        {"initial_load": "postgres_cdc.yaml", "changes": "postgres_cdc.yaml"},
        "the WAL, over the domain's own replication slot (created with the domain, so it holds every insert)",
    ),
    "mysqlcdc": (
        "mysqlcdc",
        "mysql_cdc",
        {"initial_load": "mysql_cdc_912.yaml", "changes": "mysql_cdc_913.yaml"},
        "the binlog, a replica with a server_id of its own; the head is the oldest binlog "
        "the server keeps, so what earlier runs on the container left is read and skipped "
        "too, and counts in the time",
    ),
    "db2cdc": (
        "db2cdc",
        "db2_cdc",
        {"initial_load": "db2_cdc.yaml", "changes": "db2_cdc.yaml"},
        "the CD tables asncap fills, registered with the model, before its rows",
    ),
}


def _call(domain: str, command: str, *options: str) -> dict:
    return {"name": domain, "command": command, "options": list(options)}


def own(name: str) -> str:
    """A domain of the suite's own run: ``<XP_ID>_<name>`` once read."""
    return "${xp:name(%s)}" % name


def suite(source: str, kind: str) -> list:
    system, ctype, conns, reads = SOURCES[source]
    name = f"{source}_{kind}"
    domain = own(f"{MODEL}_perf")
    per_table = BASE_SIZE * SIZE
    rows = per_table * len(TABLES)
    how = (
        f"registered with start_from=full: its snapshot is the whole {rows}"
        if kind == "initial_load"
        else f"registered from the head: the {rows} are changes it reads from {reads}"
    )
    settle = (
        ""
        if kind == "initial_load"
        else f", then a {SETTLE} pause so the source has captured the load before the stream starts"
    )
    comment = (
        f"PERFORMANCE suite: the ingestion throughput of the {source} stream source -- the "
        f"rows a stream publisher writes to its files per second, before a trigger makes them "
        f"a manifest -- over {rows} rows ({per_table} in each of the {MODEL} tables "
        f"{', '.join(TABLES)}), loaded before the stream starts so it reads a backlog. The "
        f"publisher (functions/perf_{source}.py::{name}) is {how}. STAGES: (1) domains -- create "
        f"the {system} domain, install {MODEL}, create-data --size {SIZE}; (2) collections"
        f"{settle}; (3) functions -- register the publisher, which STARTS it; (4) actions -- {SCRIPT} "
        f"reads the stream worker's log until its files hold {rows} rows or {TIME_OUT} has "
        f"passed, and says in the step's note the end-to-end figure -- rows, files, MB, seconds "
        f"from the plugin's run() to the last file, rows/s -- and the read figure -- rows the "
        f"source yielded, the seconds the plugin waited on it for them, rows/s (PARTIAL when "
        f"short; the step still passes); "
        f"(5) monitor. Generated by gen_suites.py. Run one at a time -- lanes side by side share "
        f"the machine and skew the figure: `tdd xp one-shot --suite performance/{name}`."
    )
    return [
        {"_comment": comment},
        {
            "domains": [
                _call(domain, "create", "--sys", system),
                _call(domain, "create-model", "--model", MODEL),
                _call(domain, "create-data", "--size", str(SIZE)),
            ]
        },
        {
            "collections": [
                {
                    "name": name,
                    "type": ctype,
                    "connection_template": f"connection-file:connections/{conns[kind]}",
                    "group": "sources",
                    "domains": {"D0": domain},
                }
            ]
        },
        *(
            []
            if kind == "initial_load"
            else [{"actions": [{"sleep": {"name": "settle", "time": SETTLE}}]}]
        ),
        {
            "functions": [
                {
                    "collection": name,
                    "functionpath": f"functions/perf_{source}.py::{name}",
                }
            ]
        },
        {
            "actions": [
                {
                    "python": {
                        "name": "throughput",
                        "tags": ["check"],
                        "script": SCRIPT,
                        "params": [name, "--expect", str(rows), "--time-out", TIME_OUT],
                    }
                }
            ]
        },
        {"monitor": {"time_out": "30m"}},
    ]


def kafka_suite() -> list:
    name = "kafka_json"
    domain = own("redpanda_perf")
    comment = (
        f"PERFORMANCE suite: the ingestion throughput of the Kafka stream source over JSON -- "
        f"the rows a stream publisher writes to its files per second, before a trigger makes "
        f"them a manifest -- over {KAFKA_ROWS} messages on <prefix>.employees (one partition), "
        f"each an employees row as JSON, ~130 bytes, validated against a typed JSON Schema, "
        f"written before the stream starts so it reads a backlog. The publisher "
        f"(functions/perf_kafka.py::{name}) has the CDC performance publishers' buffer and "
        f"trigger. STAGES: (1) domains -- create the redpanda domain and install the employees "
        f"model, which creates its topics; (2) actions -- {KAFKA_PASSES} passes of `modify-data "
        f"--entity employees --size {KAFKA_SIZE}`, {BASE_SIZE * KAFKA_SIZE} messages each (in "
        f"passes: one load builds every table of the model, ~12 rows for each employee sent); "
        f"(3) collections; (4) functions -- register the "
        f"publisher, which STARTS it; (5) actions -- {SCRIPT} (the stream ledger it reads is "
        f"every stream source's) reads the stream worker's log until its files hold "
        f"{KAFKA_ROWS} rows or {TIME_OUT} has passed, and says in the step's note the end-to-end "
        f"figure -- rows, files, MB, seconds from the plugin's run() to the last file, rows/s -- "
        f"and the read figure -- rows the source yielded, the seconds the plugin waited on it "
        f"for them, rows/s (PARTIAL when short; the step still passes); (6) monitor. Generated by gen_suites.py. Run one at a time: "
        f"`tdd xp one-shot --suite performance/{name}`."
    )
    return [
        {"_comment": comment},
        {
            "domains": [
                _call(domain, "create", "--sys", "redpanda"),
                _call(domain, "create-model", "--model", "employees"),
            ]
        },
        {
            "actions": [
                {
                    "loop": {
                        "name": "backlog",
                        "repeat": KAFKA_PASSES,
                        "actions": [
                            {
                                "tdd": {
                                    "name": "push",
                                    "tool": "domain",
                                    "command": "modify-data",
                                    "options": ["--domain", domain, "--entity", "employees",
                                                "--size", str(KAFKA_SIZE)],
                                }
                            }
                        ],
                    }
                }
            ]
        },
        {
            "collections": [
                {
                    "name": name,
                    "type": "kafka_topic_in",
                    "connection_template": "connection-file:connections/kafka_topic_in_perf.yaml",
                    "group": "sources",
                    "domains": {"D0": domain},
                }
            ]
        },
        {"functions": [{"collection": name, "functionpath": f"functions/perf_kafka.py::{name}"}]},
        {
            "actions": [
                {
                    "python": {
                        "name": "throughput",
                        "tags": ["check"],
                        "script": SCRIPT,
                        "params": [name, "--expect", str(KAFKA_ROWS), "--time-out", TIME_OUT],
                    }
                }
            ]
        },
        {"monitor": {"time_out": "30m"}},
    ]


def main() -> None:
    for source in SOURCES:
        for kind in ("initial_load", "changes"):
            path = SUITE / f"{source}_{kind}.json"
            path.write_text(json.dumps(suite(source, kind), indent=2) + "\n", encoding="utf-8")
            print(f"wrote {path.relative_to(SUITE)}")
    path = SUITE / "kafka_json.json"
    path.write_text(json.dumps(kafka_suite(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path.relative_to(SUITE)}")


if __name__ == "__main__":
    main()
