#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the CDC scenario suites: the same scenarios for every source in SOURCES.

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
# The run's `--profile NAME`, or nothing: on every step that reaches tdk itself.
PROFILE = "${td:profile}"
# Every set of a --trx-mode run but serial opens this many transactions at once.
CONCURRENCY = 8
TRX_MODES = ("serial", "interleaved", "nested", "mix")
# The tables a pass of quiet_table changes: all but `readings`, the quiet one.
QUIET = "readings"
BUSY = ["accounts", "ledger", "devices", "audit"]
QUIET_PASSES = 3
PAUSES = 3


class Source:
    """What a scenario needs to know of a CDC source."""

    def __init__(
        self,
        slug: str,
        system: str,
        ctype: str,
        conn: str,
        functions: str,
        initial_load: str,
        initial_load_live: str,
        keys: dict[str, str],
        logs: dict[str, str],
        keyless: list[str],
        about: str,
    ):
        self.slug = slug
        self.system = system
        self.ctype = ctype
        self.conn = conn
        self.functions = functions  # the keys variants' module
        self.initial_load = initial_load  # module::function, over a quiet start
        self.initial_load_live = initial_load_live  # module::function, under churn
        self.keys = keys  # collection -> module::function of the keys variants
        self.logs = logs  # verify_cdc_ops --cascades/--noops
        self.keyless = keyless
        self.about = about


SOURCES = {
    "postgrescdc": Source(
        slug="postgrescdc",
        system="postgrescdc",
        ctype="postgres_cdc",
        conn="postgres_cdc.yaml",
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
        about=(
            "PostgreSQL CDC over logical decoding (wal2json) of the domain's own replication "
            "slot (created with the domain, named after it, reused by the publisher); every "
            "model table REPLICA IDENTITY FULL, so the two keyless tables log their updates "
            "and deletes with whole before-images. wal2json carries the rows an ON DELETE "
            "CASCADE takes and an UPDATE that sets the values a row has: --cascades logged "
            "--noops logged"
        ),
    ),
}


# ------------------------------------------------------------------ pieces --


def own(name: str) -> str:
    """A domain of the suite's own run: ``<XP_ID>_<name>`` once read."""
    return "${xp:name(%s)}" % name


def comment(text: str) -> dict:
    return {"_comment": text}


def manifest(domain: str, system: str, data: str) -> dict:
    """A seeded domain, through one `tdd domain create --manifest`."""
    entry = {"name": domain, "system": system, "model": MODEL, "data": data}
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
                "connection_template": f"connection-file:connections/{src.conn}",
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
                PROFILE,
            ],
        }
    }


def actions(*entries: dict) -> dict:
    return {"actions": list(entries)}


def sentinel(collection: str, *keys: str, time_out: str = "5m") -> dict:
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
    params += ["--start", start, *extra, "--untracked", *UNTRACKED, PROFILE]
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
            f"register {_fn_name(src.initial_load)} (initial_load=True), which STARTS it: its "
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
            f"{_fn_name(src.initial_load)} (initial_load=True), which STARTS it; (5) sentinel "
            f"-- hold until after-create-data arrives: the load has flushed; (6) actions, "
            f"tagged live -- one `modify-data --ops Mix --sets 5` pass, then `sentinel-data "
            f"--key after-changes`; (7) sentinel; (8) actions, tagged check -- {VERIFY} "
            f"--start initial-load: the snapshot is the state the seed left, the changes after "
            f"it one by one, in the same transactions, each with its whole before-image and "
            f"the row it leaves; nothing of {', '.join(UNTRACKED)}; (9) monitor. {_run(name)}"
        ),
        manifest(d, src.system, "xs"),
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
    churn = {
        "background": {
            "name": "churn",
            "tags": ["live"],
            "actions": [
                {
                    "loop": {
                        "name": "churn-pass",
                        "repeat": 20,
                        "actions": [
                            {
                                "tdd": {
                                    "name": "change",
                                    "tool": "domain",
                                    "command": "modify-data",
                                    "options": [
                                        "--domain",
                                        d,
                                        "--ops",
                                        "Mix",
                                        "--sets",
                                        "250",
                                        *trx,
                                        "--emit-ops",
                                        OPS,
                                    ],
                                }
                            },
                            {"sleep": {"name": "pause", "time": "1s"}},
                        ],
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
            f"20 passes a second apart of `modify-data --ops Mix --sets 250 {' '.join(trx)}`, "
            f"every set one transaction of one verb over all five tables -- inserts, updates "
            f"(accounts' moving its key), deletes; it keeps running through the stages below; "
            f"(3) collections and (4) functions -- register {_fn_name(src.initial_load_live)} "
            f"(initial_load=True), which STARTS it: its load is taken over tables changing "
            f"under it; (5) actions, tagged live -- wait for churn, then `sentinel-data --key "
            f"after-churn`; (6) sentinel -- hold until both keys arrive; (7) actions, tagged "
            f"check -- {VERIFY} --check state: the load plus every change applied in commit "
            f"order as the connector deduplicates must leave each table as the whole trail "
            f"does; on the keyless tables ({', '.join(src.keyless)}) a change the load already "
            f"holds may arrive again, counted, not refused; nothing of {', '.join(UNTRACKED)}; "
            f"(8) monitor. {_run(name)}"
        ),
        manifest(d, src.system, "m"),
        actions(sentinel_data("sentinel-loaded", d, "after-create-data"), churn),
        collections(src, d, [name]),
        functions([(name, src.initial_load_live)]),
        actions(
            {"wait": {"name": "settle-wait", "tags": ["live"], "for": ["churn"]}},
            sentinel_data("sentinel-churned", d, "after-churn"),
        ),
        sentinel(name, "after-create-data", "after-churn"),
        actions(
            verify(src, "verify-ops", name, "initial-load", "--check", "state", "--keyless", *src.keyless)
        ),
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
            f"(initial_load=True); (5) sentinel -- the load has flushed; then {QUIET_PASSES} "
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
        manifest(d, src.system, "xs"),
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
            f"registering a stream publisher STARTS it; (4) actions, tagged live -- a 30s "
            f"pause for the tail streams to attach (a change before that is not theirs to "
            f"see), one `modify-data --ops Mix --sets 30` pass (inserts, updates -- accounts' "
            f"moving its key, ledger's by both columns of its key, devices' by its unique "
            f"index, readings' by every column -- and deletes), then `sentinel-data --key "
            f"after-changes`; (5) sentinel -- hold until after-changes is in {checked[0]} and "
            f"{checked[1]}; (6) actions, tagged check -- {VERIFY} checks both from the tail, "
            f"one change at a time with its whole before-image and the row it leaves, nothing "
            f"of {', '.join(UNTRACKED)} (each its own lane: one failing does not hide the "
            f"other); {colls[2]} and {colls[3]} run over the same changes, unchecked: their "
            f"rows nest the values the check reads flat; (7) monitor. {_run(name)}"
        ),
        manifest(d, src.system, "xs"),
        collections(src, d, colls),
        functions(list(src.keys.items())),
        actions(
            {"sleep": {"name": "attach", "tags": ["live"], "time": "30s"}},
            modify("change", d, 30),
            sentinel_data("sentinel-changed", d, "after-changes"),
        ),
        {"sentinel": [s for c in checked for s in sentinel(c, "after-changes")["sentinel"]]},
        actions(*(verify(src, f"verify-{c}", c, "tail", cont=True) for c in checked)),
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
            f"(initial_load=True); (5) sentinel -- the load has flushed; then {PAUSES} times: "
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
        manifest(d, src.system, "xs"),
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
