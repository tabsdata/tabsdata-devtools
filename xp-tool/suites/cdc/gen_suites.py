#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the CDC scenario suites: the same scenarios for every source in SOURCES --
postgrescdc, mysqlcdc and db2cdc.

    python suites/cdc/gen_suites.py

Every suite runs over a domain of the ``employeescdc`` model -- one table per way a
row is identified: ``accounts`` (a primary key every update CHANGES), ``ledger`` (a
composite primary key), ``devices`` (no primary key, a unique index), ``readings``
(no primary key and no index) -- plus ``audit``, a plain-keyed table every data
command changes and no stream here tracks, and ``xp_sentinel``. Every data command
appends what it applied to ``${xp:dir}/ops.jsonl`` (``--emit-ops``), and
``scripts/verify_cdc_ops.py`` checks the stream's output against that trail, with
``--untracked audit``: a stream must carry every tracked change and nothing of the
untracked table.

The scenarios, ``<source>_<scenario>``:

- ``from_empty``: the model installed and NO data when the stream starts; then the
  seed and a modify-data pass -- everything arrives as changes, from zero.
- ``initial_load``: the stream starts over a seeded database; its initial load must
  be the database, and the changes after it arrive one by one.
- ``initial_load_live_<mode>``, mode ``serial``, ``interleaved``, ``nested``,
  ``mix``: the initial load is taken while modify-data churns, its transactions
  applied ``--trx-mode <mode>`` -- the load and the changes after it must hold
  every change, whatever the transactions' shape.
- ``quiet_table``: ``readings`` is left alone for several rollovers -- each pass of
  changes to the other tables waited for in a version of its own -- then changed.
- ``keys``: every key shape a stream must get right, over four variants of the
  publisher (from the tail, from the head, struct columns, map columns).
- ``pause_resume``: the publisher is disabled, the database changes, the publisher
  is enabled -- three times; it must resume where it stopped, nothing lost or
  repeated.

Change SOURCES or a scenario here and re-run; never edit the JSONs by hand.
"""

from __future__ import annotations

import json
from pathlib import Path

SUITE = Path(__file__).resolve().parent
MODEL = "employeescdc"
OPS = "${xp:dir}/ops.jsonl"
VERIFY = "scripts/verify_cdc_ops.py"
UNTRACKED = ["audit"]
# The run's profile name, or "" without one: `--profile` on every step that
# reaches tdk itself.
PROFILE = "${td:profile}"
# Every set of a --trx-mode run but serial opens this many transactions at once.
CONCURRENCY = 8
TRX_MODES = ("serial", "interleaved", "nested", "mix")
# The tables a pass of quiet_table changes: all but `readings`, the quiet one.
QUIET = "readings"
BUSY = ["accounts", "ledger", "devices", "audit"]
QUIET_PASSES = 3
# The model's table with no key and no index: an UPDATE or DELETE scans it whole.
SCANNED = "readings"
SCANNED_REST = ["accounts", "ledger", "devices", "audit"]
PAUSES = 3
# A tail stream sees only what is written after it attached, which takes as long as
# the instance takes to start its streamer: seconds alone, minutes under a full run.
# So it is waited for, not guessed: probes every ATTACH_PROBE until one arrives.
ATTACH_KEY = "attached"
ATTACH_PROBE = "20s"
ATTACH_TIME_OUT = "20m"
# How long a sentinel waits for its key. A bound for a failure, not a pace: a key that
# arrives ends the wait. Under a full run (`--suite ALL`, about 100 lanes) a stream's
# first flush was triggered 45s after its manifest and committed 10.5 min later (the
# function busy all the while), so 5m failed lanes whose stream was fine.
SENTINEL_TIME_OUT = "20m"


class Source:
    """What a scenario needs to know of a CDC source."""

    def __init__(
        self,
        slug: str,
        system: str,
        ctype: str,
        conns: dict[str, str],
        functions: str,
        initial_load: str,
        initial_load_live: str,
        keys: dict[str, str],
        logs: dict[str, str],
        keyless: list[str],
        head_start: str,
        head_note: str,
        about: str,
        scan_locks: bool = False,
    ):
        self.slug = slug
        self.system = system
        self.ctype = ctype
        self.conns = conns  # collection -> connection template; "*" for the rest
        self.functions = functions  # the keys variants' module
        self.initial_load = initial_load  # module::function, over a quiet start
        self.initial_load_live = initial_load_live  # module::function, under churn
        self.keys = keys  # collection -> module::function of the keys variants
        self.logs = logs  # verify_cdc_ops --cascades/--noops
        self.keyless = keyless  # --check state's --keyless; none where loads never repeat
        self.head_start = head_start  # how the keys suite's head variant is checked
        self.head_note = head_note
        self.about = about
        # A DELETE locks every row it scans (`tdd domain` refuses a schedule
        # that would wait on its own run): the interleaved and mix churns change
        # SCANNED in a serial pass of its own, after the concurrent one.
        self.scan_locks = scan_locks

    def conn(self, collection: str) -> str:
        return self.conns.get(collection, self.conns["*"])


SOURCES = {
    "postgrescdc": Source(
        slug="postgrescdc",
        system="postgrescdc",
        ctype="postgres_cdc",
        conns={"*": "postgres_cdc.yaml"},
        functions="functions/caps_postgrescdc.py",
        initial_load="functions/caps_postgrescdc_initial_load.py::postgrescdc_initial_load",
        initial_load_live="functions/caps_postgrescdc_initial_load.py::postgrescdc_initial_load_live",
        keys={
            "postgrescdc_in": "functions/caps_postgrescdc.py::postgrescdc_in",
            "postgrescdc_head": "functions/caps_postgrescdc.py::postgrescdc_in_head",
            "postgrescdc_struct": "functions/caps_postgrescdc.py::postgrescdc_in_struct",
            "postgrescdc_map": "functions/caps_postgrescdc.py::postgrescdc_in_map",
        },
        logs={"--cascades": "logged", "--noops": "logged"},
        keyless=["devices", "readings"],
        head_start="tail",
        head_note=(
            "as a tail too: each variant creates its own slot when it registers, and logical "
            "decoding keeps no WAL from before a slot, so its head is where it attached"
        ),
        about=(
            "PostgreSQL CDC over logical decoding (wal2json) of the domain's own replication "
            "slot (created with the domain, named after it, reused by the publisher); every "
            "model table REPLICA IDENTITY FULL, so the two keyless tables log their updates "
            "and deletes with whole before-images. wal2json carries the rows an ON DELETE "
            "CASCADE takes and an UPDATE that sets the values a row has: --cascades logged "
            "--noops logged"
        ),
    ),
    "mysqlcdc": Source(
        slug="mysqlcdc",
        system="mysqlcdc",
        ctype="mysql_cdc",
        # MySQL admits one replica per server_id and every registered publisher is one,
        # so every collection that may run beside another has an id of its own: the
        # keys variants 512-515, the single-collection suites the 81x block.
        conns={
            "*": "mysql_cdc.yaml",
            "mysqlcdc_head": "mysql_cdc_513.yaml",
            "mysqlcdc_struct": "mysql_cdc_514.yaml",
            "mysqlcdc_map": "mysql_cdc_515.yaml",
            "mysqlcdc_initial_load": "mysql_cdc_812.yaml",
            "mysqlcdc_initial_load_live_serial": "mysql_cdc_813.yaml",
            "mysqlcdc_initial_load_live_interleaved": "mysql_cdc_814.yaml",
            "mysqlcdc_initial_load_live_nested": "mysql_cdc_815.yaml",
            "mysqlcdc_initial_load_live_mix": "mysql_cdc_816.yaml",
            "mysqlcdc_from_empty": "mysql_cdc_817.yaml",
            "mysqlcdc_quiet_table": "mysql_cdc_818.yaml",
            "mysqlcdc_pause_resume": "mysql_cdc_819.yaml",
        },
        functions="functions/caps_mysqlcdc.py",
        initial_load="functions/caps_mysqlcdc_initial_load.py::mysqlcdc_initial_load",
        initial_load_live="functions/caps_mysqlcdc_initial_load.py::mysqlcdc_initial_load_live",
        keys={
            "mysqlcdc_in": "functions/caps_mysqlcdc.py::mysqlcdc_in",
            "mysqlcdc_head": "functions/caps_mysqlcdc.py::mysqlcdc_in_head",
            "mysqlcdc_struct": "functions/caps_mysqlcdc.py::mysqlcdc_in_struct",
            "mysqlcdc_map": "functions/caps_mysqlcdc.py::mysqlcdc_in_map",
        },
        logs={"--cascades": "unlogged", "--noops": "unlogged"},
        keyless=[],
        head_start="head",
        head_note=(
            "from the head: it replays the binlog, the create-data seed first, so the seed "
            "is checked as a snapshot is"
        ),
        about=(
            "MySQL CDC over the binlog (ROW format, FULL row images, gtid_mode=ON), each "
            "publisher a replica with a server_id of its own; a change to a keyless table "
            "names its row by every column. The binlog has no row for what an ON DELETE "
            "CASCADE takes and no event for an UPDATE that changes nothing: --cascades "
            "unlogged --noops unlogged. An initial load pins its GTID position under a brief "
            "global read lock, so no change is both loaded and replayed"
        ),
        scan_locks=True,
    ),
    "db2cdc": Source(
        slug="db2cdc",
        system="db2cdc",
        ctype="db2_cdc",
        conns={"*": "db2_cdc.yaml"},
        functions="functions/caps_db2cdc.py",
        initial_load="functions/caps_db2cdc_initial_load.py::db2cdc_initial_load",
        initial_load_live="functions/caps_db2cdc_initial_load.py::db2cdc_initial_load_live",
        keys={
            "db2cdc_in": "functions/caps_db2cdc.py::db2cdc_in",
            "db2cdc_head": "functions/caps_db2cdc.py::db2cdc_in_head",
            "db2cdc_struct": "functions/caps_db2cdc.py::db2cdc_in_struct",
            "db2cdc_map": "functions/caps_db2cdc.py::db2cdc_in_map",
        },
        logs={"--cascades": "logged", "--noops": "unlogged"},
        keyless=["devices", "readings"],
        head_start="head",
        head_note=(
            "from the head: it replays each CD table from its origin, the create-data seed "
            "first (the tables are registered before it is loaded)"
        ),
        about=(
            "Db2 CDC over the ASN SQL-Replication CD tables the db2cdc system registers for "
            "every model table, asncap copying each change a moment after it commits; "
            "column names arrive upper-cased and are matched without case. The CD tables "
            "carry the rows an ON DELETE CASCADE takes but not an UPDATE that changes "
            "nothing: --cascades logged --noops unlogged. Db2 has no snapshot isolation, so "
            "an initial load under changes may load a change and replay it too"
        ),
        scan_locks=True,
    ),
}


# ------------------------------------------------------------------ pieces --


def own(name: str) -> str:
    """A domain of the suite's own run: ``<XP_ID>_<name>`` once read."""
    return "${xp:name(%s)}" % name


def comment(text: str) -> dict:
    return {"_comment": text}


def manifest(domain: str, system: str, size: int) -> dict:
    """A seeded domain, through one `tdd domain create --manifest`; `size` is
    `create-data --size` (~size x 100 rows)."""
    entry = {"name": domain, "system": system, "model": MODEL, "size": size}
    return {"domain-manifest": {"emit_ops": OPS, "domains": [entry]}}


def unseeded(domain: str, system: str) -> dict:
    """A domain holding the model and no data: `tdd domain` calls, since a
    manifest entry with a model is always seeded (xs when it names no size)."""
    return {
        "domains": [
            {"name": domain, "command": "create", "options": ["--sys", system]},
            {"name": domain, "command": "create-model", "options": ["--model", MODEL]},
        ]
    }


def collections(src: Source, domain: str, names: list[str]) -> dict:
    return {
        "collections": [
            {
                "name": n,
                "type": src.ctype,
                "connection_template": f"connection-file:connections/{src.conn(n)}",
                "group": "sources",
                "domains": {"D0": domain},
            }
            for n in names
        ]
    }


def functions(entries: list[tuple[str, str]]) -> dict:
    return {"functions": [{"collection": c, "functionpath": f} for c, f in entries]}


def domain_call(name: str, domain: str, command: str, *options: str) -> dict:
    return {
        "tdd": {
            "name": name,
            "tags": ["live"],
            "tool": "domain",
            "command": command,
            "options": ["--domain", domain, *options, "--emit-ops", OPS],
        }
    }


def sentinel_data(name: str, domain: str, key: str) -> dict:
    return domain_call(name, domain, "sentinel-data", "--key", key)


def modify(name: str, domain: str, sets: int, *extra: str) -> dict:
    return domain_call(name, domain, "modify-data", "--ops", "Mix", "--sets", str(sets), *extra)


def tdk_fn(name: str, verb: str, collection: str, function: str) -> dict:
    # tdk itself, through its launcher: `tdd xp disable-function` is a whole xp
    # run of its own, which a step inside one does not need.
    return {
        "tdd": {
            "name": name,
            "tags": ["live"],
            "tool": "tdk",
            "command": "fn",
            "options": [
                verb,
                "--proj",
                "${xp:project}",
                "--coll",
                collection,
                "--name",
                function,
                "--profile",
                PROFILE,
            ],
        }
    }


def actions(*entries: dict) -> dict:
    return {"actions": list(entries)}


def attached(domain: str, *collections: str) -> dict:
    """A sentinel per stream, holding until it has attached: xp writes a fresh
    `attached-<n>-<random>` sentinel into the domain every ATTACH_PROBE, onto the
    trail like every other change, until one arrives (the probe)."""
    return {
        "sentinel": [
            {
                "collection": c,
                "table": "xp_sentinel_changes",
                "wait_for_key": ATTACH_KEY,
                "time_out": ATTACH_TIME_OUT,
                "probe": {"domain": domain, "every": ATTACH_PROBE, "emit_ops": OPS},
            }
            for c in collections
        ]
    }


def sentinel(collection: str, *keys: str, time_out: str = SENTINEL_TIME_OUT) -> dict:
    return {
        "sentinel": [
            {
                "collection": collection,
                "table": "xp_sentinel_changes",
                "wait_for_key": k,
                "time_out": time_out,
            }
            for k in keys
        ]
    }


def verify(src: Source, name: str, collection: str, start: str, *extra: str, cont: bool = False) -> dict:
    params = [OPS, collection]
    for flag, value in src.logs.items():
        params += [flag, value]
    params += ["--start", start, *extra, "--untracked", *UNTRACKED, "--profile", PROFILE]
    body = {"name": name, "tags": ["check"], "script": VERIFY, "params": params}
    if cont:
        body["continue_on_fail"] = True
    return {"python": body}


def monitor() -> dict:
    return {"monitor": {"time_out": "30m"}}


def _fn_name(path: str) -> str:
    return path.split("::", 1)[1]


def _run(name: str) -> str:
    return f"Generated by gen_suites.py. Run: `tdd xp one-shot --suite cdc/{name} --keep`."


# --------------------------------------------------------------- scenarios --


def from_empty(src: Source) -> list:
    name = f"{src.slug}_from_empty"
    d = own(f"{MODEL}_empty")
    return [
        comment(
            f"CDC scenario FROM EMPTY: {src.about}. The model is installed and holds NO data "
            f"when the stream starts, so everything it carries arrives as changes, from zero. "
            f"STAGES: (1) domains -- create the {src.system} domain and install {MODEL}, no "
            f"create-data; (2) actions, tagged live -- `sentinel-data --key before-stream`, "
            f"the one row the stream's initial load finds; (3) collections and (4) functions -- "
            f"register {_fn_name(src.initial_load)} (start_from=full), which STARTS it: its "
            f"load is the empty tables and that sentinel; (5) sentinel -- hold until "
            f"before-stream arrives, so the load is done before any data exists; (6) actions, "
            f"tagged live -- the seed (`create-data --size 1`, one transaction), one "
            f"`modify-data --ops Mix --sets 10` pass, `sentinel-data --key after-changes`; "
            f"(7) sentinel -- hold until after-changes arrives; (8) actions, tagged check -- "
            f"{VERIFY} --start initial-load: the load holds the sentinel alone, and the seed "
            f"and every change after it arrive one by one, in their transactions, nothing of "
            f"{', '.join(UNTRACKED)}; (9) monitor. {_run(name)}"
        ),
        unseeded(d, src.system),
        actions(sentinel_data("sentinel-empty", d, "before-stream")),
        collections(src, d, [name]),
        functions([(name, src.initial_load)]),
        sentinel(name, "before-stream"),
        actions(
            domain_call("seed", d, "create-data", "--size", "1"),
            modify("change", d, 10),
            sentinel_data("sentinel-changed", d, "after-changes"),
        ),
        sentinel(name, "after-changes"),
        actions(verify(src, "verify-ops", name, "initial-load")),
        monitor(),
    ]


def initial_load(src: Source) -> list:
    name = f"{src.slug}_initial_load"
    d = own(f"{MODEL}_xs")
    return [
        comment(
            f"CDC scenario INITIAL LOAD: {src.about}. The stream starts over a seeded "
            f"database: its initial load must be the database, and the changes after it the "
            f"operations modify-data applied. STAGES: (1) domains -- create the {src.system} "
            f"domain, install {MODEL}, load the xs seed, its operations appended to {OPS}; "
            f"(2) actions, tagged live -- `sentinel-data --key after-create-data`, so the load "
            f"carries a key; (3) collections and (4) functions -- register "
            f"{_fn_name(src.initial_load)} (start_from=full), which STARTS it; (5) sentinel "
            f"-- hold until after-create-data arrives: the load has flushed; (6) actions, "
            f"tagged live -- one `modify-data --ops Mix --sets 5` pass, then `sentinel-data "
            f"--key after-changes`; (7) sentinel; (8) actions, tagged check -- {VERIFY} "
            f"--start initial-load: the snapshot is the state the seed left, the changes after "
            f"it one by one, in the same transactions, each with its whole before-image and "
            f"the row it leaves; nothing of {', '.join(UNTRACKED)}; (9) monitor. {_run(name)}"
        ),
        manifest(d, src.system, 1),
        actions(sentinel_data("sentinel", d, "after-create-data")),
        collections(src, d, [name]),
        functions([(name, src.initial_load)]),
        sentinel(name, "after-create-data"),
        actions(modify("change", d, 5), sentinel_data("sentinel-changed", d, "after-changes")),
        sentinel(name, "after-changes"),
        actions(verify(src, "verify-ops", name, "initial-load")),
        monitor(),
    ]


def initial_load_live(src: Source, mode: str) -> list:
    name = f"{src.slug}_initial_load_live_{mode}"
    d = own(f"{MODEL}_m")
    trx = ["--trx-mode", mode] + ([] if mode == "serial" else ["--trx-concurrency", str(CONCURRENCY)])
    shape = {
        "serial": "one transaction at a time",
        "interleaved": f"{CONCURRENCY} open at once, a statement from each in turn, each "
        f"committing after its last",
        "nested": f"nests {CONCURRENCY} deep, each begun inside the one before it and "
        f"committed inside it too -- commits in reverse start order",
        "mix": f"groups of {CONCURRENCY}, each the next of serial, interleaved, nested",
    }[mode]
    if src.keyless:
        keyless = (
            f"on the keyless tables ({', '.join(src.keyless)}) a change the load already "
            f"holds may arrive again, counted, not refused"
        )
        keyless_args = ["--keyless", *src.keyless]
    else:
        keyless = "no change the load holds arrives again, on any table"
        keyless_args = []
    split = src.scan_locks and mode in ("interleaved", "mix")

    def change(name: str, *options: str) -> dict:
        return {
            "tdd": {
                "name": name,
                "tool": "domain",
                "command": "modify-data",
                "options": ["--domain", d, "--ops", "Mix", *options, "--emit-ops", OPS],
            }
        }

    if split:
        pass_steps = [
            change("change", "--sets", "250", "--entity", ",".join(SCANNED_REST), *trx),
            change("change-scanned", "--sets", "250", "--entity", SCANNED),
        ]
        how = (
            f"`modify-data --ops Mix --sets 250 --entity {','.join(SCANNED_REST)} "
            f"{' '.join(trx)}`, then `modify-data --ops Mix --sets 250 --entity {SCANNED}` "
            f"serially -- {SCANNED} has no key and no index, a DELETE scans it whole, and "
            f"this source locks every row a DELETE scans, so one beside another open "
            f"transaction's writes there would wait on its own run (nested never meets one: "
            f"its transactions all begin on accounts)"
        )
    else:
        pass_steps = [change("change", "--sets", "250", *trx)]
        how = f"`modify-data --ops Mix --sets 250 {' '.join(trx)}`"
    churn = {
        "background": {
            "name": "churn",
            "tags": ["live"],
            "actions": [
                {
                    "loop": {
                        "name": "churn-pass",
                        "repeat": 20,
                        "actions": [*pass_steps, {"sleep": {"name": "pause", "time": "1s"}}],
                    }
                }
            ],
        }
    }
    return [
        comment(
            f"CDC scenario INITIAL LOAD UNDER LIVE CHANGES, --trx-mode {mode}: {src.about}. "
            f"The initial load is taken while modify-data churns, its transactions {shape}. "
            f"STAGES: (1) domains -- create the {src.system} domain, install {MODEL}, load the "
            f"m seed (10k rows a table), its operations appended to {OPS}; (2) actions, tagged "
            f"live -- `sentinel-data --key after-create-data`, then `churn` in the background: "
            f"20 passes a second apart of {how}, "
            f"every set one transaction of one verb over its tables -- inserts, updates "
            f"(accounts' moving its key), deletes; it keeps running through the stages below; "
            f"(3) collections and (4) functions -- register {_fn_name(src.initial_load_live)} "
            f"(start_from=full), which STARTS it: its load is taken over tables changing "
            f"under it; (5) actions, tagged live -- wait for churn, then `sentinel-data --key "
            f"after-churn`; (6) sentinel -- hold until both keys arrive; (7) actions, tagged "
            f"check -- {VERIFY} --check state: the load plus every change applied in commit "
            f"order as the connector deduplicates must leave each table as the whole trail "
            f"does; {keyless}; nothing of {', '.join(UNTRACKED)}; "
            f"(8) monitor. {_run(name)}"
        ),
        manifest(d, src.system, 100),
        actions(sentinel_data("sentinel-loaded", d, "after-create-data"), churn),
        collections(src, d, [name]),
        functions([(name, src.initial_load_live)]),
        actions(
            {"wait": {"name": "settle-wait", "tags": ["live"], "for": ["churn"]}},
            sentinel_data("sentinel-churned", d, "after-churn"),
        ),
        sentinel(name, "after-create-data", "after-churn"),
        actions(verify(src, "verify-ops", name, "initial-load", "--check", "state", *keyless_args)),
        monitor(),
    ]


def quiet_table(src: Source) -> list:
    name = f"{src.slug}_quiet_table"
    d = own(f"{MODEL}_xs")
    stages: list = [
        comment(
            f"CDC scenario QUIET TABLE: {src.about}. `{QUIET}` is tracked and left alone for "
            f"{QUIET_PASSES} rollovers, then changed: a slot that carried nothing for several "
            f"versions must still carry its table's changes, and the tables around it every "
            f"one of theirs. STAGES: (1) domains -- create the {src.system} domain, install "
            f"{MODEL}, load the xs seed; (2) actions -- `sentinel-data --key after-create-data`; "
            f"(3) collections and (4) functions -- register {_fn_name(src.initial_load)} "
            f"(start_from=full); (5) sentinel -- the load has flushed; then {QUIET_PASSES} "
            f"times: actions -- `modify-data --entity {','.join(BUSY)} --ops Mix --sets 6` and "
            f"`sentinel-data --key quiet-<n>`, and a sentinel stage holding until quiet-<n> "
            f"arrives, so each pass is published in a version of its own before the next "
            f"starts -- a rollover with nothing for {QUIET}; after the second pass a 75s pause, "
            f"past the publisher's 1-minute fallback window, with nothing changing at all; "
            f"then actions -- `modify-data --entity {QUIET} --ops Mix --sets 6`, one more "
            f"`modify-data --ops Mix --sets 6` over every table, `sentinel-data --key "
            f"after-changes`; a sentinel; actions, tagged check -- {VERIFY} --start "
            f"initial-load: every change one by one in its transaction, nothing of "
            f"{', '.join(UNTRACKED)}; monitor. {_run(name)}"
        ),
        manifest(d, src.system, 1),
        actions(sentinel_data("sentinel", d, "after-create-data")),
        collections(src, d, [name]),
        functions([(name, src.initial_load)]),
        sentinel(name, "after-create-data"),
    ]
    for n in range(1, QUIET_PASSES + 1):
        steps = [
            modify(f"busy-{n}", d, 6, "--entity", ",".join(BUSY)),
            sentinel_data(f"sentinel-quiet-{n}", d, f"quiet-{n}"),
        ]
        if n == 2:
            steps.append({"sleep": {"name": "idle", "tags": ["live"], "time": "75s"}})
        stages += [actions(*steps), sentinel(name, f"quiet-{n}")]
    stages += [
        actions(
            modify("wake", d, 6, "--entity", QUIET),
            modify("change", d, 6),
            sentinel_data("sentinel-changed", d, "after-changes"),
        ),
        sentinel(name, "after-changes"),
        actions(verify(src, "verify-ops", name, "initial-load")),
        monitor(),
    ]
    return stages


def keys(src: Source) -> list:
    name = f"{src.slug}_keys"
    d = own(f"{MODEL}_xs")
    colls = list(src.keys)
    checked = colls[:2]  # the tail and the head; struct and map nest what the check reads flat
    return [
        comment(
            f"CDC scenario KEYS: {src.about}. Every way a row is identified, over four "
            f"variants of the publisher ({src.functions}), each in its own collection: "
            f"{colls[0]} (start_from=tail, flattened rows), {colls[1]} (start_from=head), "
            f"{colls[2]} (columns_format=struct, flatten_columns=False), {colls[3]} "
            f"(columns_format=map). STAGES: (1) domains -- create the {src.system} domain, "
            f"install {MODEL}, load the xs seed; (2) collections and (3) functions -- "
            f"registering a stream publisher STARTS it; (4) sentinel -- hold until {checked[0]} "
            f"and {checked[1]} have attached (a change before that is not theirs to see): a "
            f"probe writes `sentinel-data --key {ATTACH_KEY}-<n>-<random>` every "
            f"{ATTACH_PROBE}, at most {ATTACH_TIME_OUT}, until one arrives in each; (5) "
            f"actions, tagged live -- one `modify-data --ops Mix --sets 30` pass (inserts, "
            f"updates -- accounts' moving its key, ledger's by both columns of its key, "
            f"devices' by its unique index, readings' by every column -- and deletes), then "
            f"`sentinel-data --key after-changes`; (6) sentinel -- hold until after-changes "
            f"is in {checked[0]} and {checked[1]}; (7) actions, tagged check -- {VERIFY} "
            f"checks {checked[0]} from the "
            f"tail and {checked[1]} {src.head_note}, one change at a time with its whole "
            f"before-image and the row it leaves, nothing "
            f"of {', '.join(UNTRACKED)} (each its own lane: one failing does not hide the "
            f"other); {colls[2]} and {colls[3]} run over the same changes, unchecked: their "
            f"rows nest the values the check reads flat; (8) monitor. {_run(name)}"
        ),
        manifest(d, src.system, 1),
        collections(src, d, colls),
        functions(list(src.keys.items())),
        attached(d, *checked),
        actions(
            modify("change", d, 30),
            sentinel_data("sentinel-changed", d, "after-changes"),
        ),
        {"sentinel": [s for c in checked for s in sentinel(c, "after-changes")["sentinel"]]},
        actions(
            verify(src, f"verify-{checked[0]}", checked[0], "tail", cont=True),
            verify(src, f"verify-{checked[1]}", checked[1], src.head_start, cont=True),
        ),
        monitor(),
    ]


def pause_resume(src: Source) -> list:
    name = f"{src.slug}_pause_resume"
    d = own(f"{MODEL}_xs")
    fn = _fn_name(src.initial_load)
    stages: list = [
        comment(
            f"CDC scenario PAUSE AND RESUME: {src.about}. The publisher is disabled, the "
            f"database changes, the publisher is enabled -- {PAUSES} times. Enabled again it "
            f"must resume where it stopped: no change lost, none delivered twice, the initial "
            f"load not taken again. STAGES: (1) domains -- create the {src.system} domain, "
            f"install {MODEL}, load the xs seed; (2) actions -- `sentinel-data --key "
            f"after-create-data`; (3) collections and (4) functions -- register {fn} "
            f"(start_from=full); (5) sentinel -- the load has flushed; then {PAUSES} times: "
            f"actions -- `tdd tdk fn disable`, a 20s pause for the worker to stop, `modify-data "
            f"--ops Mix --sets 6` and `sentinel-data --key paused-<n>` while it is down, `tdd "
            f"tdk fn enable`; a sentinel stage holding until paused-<n> arrives; then actions "
            f"-- one more pass with the publisher running and `sentinel-data --key "
            f"after-changes`; a sentinel; actions, tagged check -- {VERIFY} --start "
            f"initial-load: one load, and every change after it once, in its transaction, in "
            f"commit order -- a resume that replayed or skipped is a transaction too many or "
            f"too few; nothing of {', '.join(UNTRACKED)}; monitor. The tdk steps and the "
            f"check take {PROFILE}: the run's --profile, or tdk's default. {_run(name)}"
        ),
        manifest(d, src.system, 1),
        actions(sentinel_data("sentinel", d, "after-create-data")),
        collections(src, d, [name]),
        functions([(name, src.initial_load)]),
        sentinel(name, "after-create-data"),
    ]
    for n in range(1, PAUSES + 1):
        stages += [
            actions(
                tdk_fn(f"disable-{n}", "disable", name, fn),
                {"sleep": {"name": f"stopping-{n}", "tags": ["live"], "time": "20s"}},
                modify(f"change-paused-{n}", d, 6),
                sentinel_data(f"sentinel-paused-{n}", d, f"paused-{n}"),
                tdk_fn(f"enable-{n}", "enable", name, fn),
            ),
            sentinel(name, f"paused-{n}"),
        ]
    stages += [
        actions(modify("change", d, 6), sentinel_data("sentinel-changed", d, "after-changes")),
        sentinel(name, "after-changes"),
        actions(verify(src, "verify-ops", name, "initial-load")),
        monitor(),
    ]
    return stages


def suites(src: Source) -> dict[str, list]:
    out = {
        f"{src.slug}_from_empty": from_empty(src),
        f"{src.slug}_initial_load": initial_load(src),
        f"{src.slug}_quiet_table": quiet_table(src),
        f"{src.slug}_keys": keys(src),
        f"{src.slug}_pause_resume": pause_resume(src),
    }
    for mode in TRX_MODES:
        out[f"{src.slug}_initial_load_live_{mode}"] = initial_load_live(src, mode)
    return out


def main() -> None:
    for src in SOURCES.values():
        for name, doc in suites(src).items():
            path = SUITE / f"{name}.json"
            path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
            print(f"wrote {path.relative_to(SUITE)}")


if __name__ == "__main__":
    main()
