#
# Copyright 2026 Tabsdata Inc.
#

"""The bronze model's changes: every table takes what its arrival pattern
means, on every nature of system, and each run continues the state the seed and
the earlier runs left -- unique sim_counters, a data_ts past every earlier one,
the CDC contract, a snapshot file that is the state, the next period, the log's
next lines -- and kafka carries every table as Avro or Protobuf but the CDC one.
No system is reached: a file domain stages under a temporary folder, a kafka
domain's producer is a fake."""

import argparse
import json
import random

import pytest
from tabsdata_dev.common.systems import constants, datagen, descriptor, emit
from tabsdata_dev.common.systems.datagen import ChangeSpec, OpKind, OpSelector
from tabsdata_dev.common.systems.errors import TdxError

MODEL = "bronze"
FULL, SOFT, NO_DELETE = (
    "brz_full_snapshot",
    "brz_insup_soft_delete",
    "brz_insup_no_delete",
)
CDC, APPEND = "brz_cdc_stream", "brz_append_events"
PERIOD, LOG = "brz_period_snapshot", "brz_log_lines"
TABLES = [FULL, SOFT, NO_DELETE, CDC, APPEND, PERIOD, LOG]
INSERT_BASE = 10_000_000


@pytest.fixture(scope="module")
def seed():
    """The size-1 seed, by table."""
    tables = datagen.load_model(MODEL).build_initial(
        random.Random(datagen.INITIAL_SEED), datagen.BASE_SIZE
    )
    return {t.name: t for t in tables}


def _spec(seed_no, ops=OpSelector.MIX, sets=3, entities=None, rows=None):
    model = datagen.load_model(MODEL)
    names = entities or [e.table for e in model.entities]
    per = rows or {e.table: e.rows_per_set for e in model.entities}
    return ChangeSpec(
        names, ops, sets, {n: per[n] for n in names}, seed_no, seed_no * 1000
    )


def _runs(seed, count, verbs=None, **kw):
    """`count` consecutive AUTO runs (seeds 1..count), each planned by a model
    of its own from the runs before it, as modify-data does."""
    counts = {name: len(t.rows) for name, t in seed.items()}
    history, out = [], []
    for s in range(1, count + 1):
        spec = _spec(s, **kw)
        out.append(
            datagen.plan(
                datagen.load_model(MODEL),
                spec,
                counts,
                history=list(history),
                verbs=verbs,
            )
        )
        history.append(ChangeSpec.from_dict(spec.to_dict()))
    return out


def _changes(txns, table=None, kind=None):
    return [
        c
        for t in txns
        for c in t
        if (table is None or c.table == table) and (kind is None or c.kind is kind)
    ]


def _apply(rows: dict[int, dict], changes) -> None:
    """What a SQL table does with the changes: rows by sim_counter."""
    for c in changes:
        if c.kind is OpKind.INSERT:
            assert c.row["sim_counter"] not in rows, c.row
            rows[c.row["sim_counter"]] = dict(c.row)
        elif c.kind is OpKind.UPDATE:
            assert c.where["sim_counter"] in rows, c.where
            rows[c.where["sim_counter"]].update(c.set_values)
        else:
            assert c.where["sim_counter"] in rows, c.where
            del rows[c.where["sim_counter"]]


# ---- the seed ---------------------------------------------------------------


def test_the_seed_adds_a_period_snapshot_and_a_log(seed):
    assert list(seed) == TABLES
    assert datagen.entities_of(MODEL) == [*TABLES, datagen.SENTINEL_ENTITY]
    for name in (FULL, SOFT, NO_DELETE, CDC, APPEND, LOG):
        assert [r["sim_counter"] for r in seed[name].rows] == list(range(1, 10_001))
    period = seed[PERIOD].rows
    ends = sorted({r["period_end"] for r in period})
    assert [d.isoformat() for d in ends] == ["2024-10-31", "2024-11-30", "2024-12-31"]
    first = [r for r in period if r["period_end"] == ends[0]]
    assert len(first) == datagen.BASE_SIZE  # n keys at the first month-end
    for end in ends:
        keys = [
            (r["tenant_id"], r["entity_id"]) for r in period if r["period_end"] == end
        ]
        assert len(keys) == len(set(keys))  # one row per key per period
        assert all(
            r["data_ts"][:7] == end.isoformat()[:7]
            for r in period
            if r["period_end"] == end
        )
    lines = seed[LOG].rows
    assert lines[24]["line"].startswith("    at ") and lines[24]["ts"] is None
    assert lines[0]["line"].startswith(lines[0]["ts"].replace(" ", "T") + ".000Z")
    assert max(r["ts"] for r in lines if r["ts"]) < "2025"
    assert emit.formats_of(seed[LOG]) == (emit.LOG_FORMAT,)


# ---- R1: every table, its verbs, unique counters, a later data_ts ----------


def test_each_table_takes_its_patterns_verbs_on_each_nature():
    from tabsdata_dev.common.systems.systems.fs.backend import Fs
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda

    by = {e.table: e for e in datagen.load_model(MODEL).entities}
    assert list(by) == TABLES
    i, u, d = OpKind.INSERT, OpKind.UPDATE, OpKind.DELETE
    sql = {FULL: (i, u, d), SOFT: (i, u), NO_DELETE: (i, u, d)}
    files = {FULL: (i, u, d)}
    for name, entity in by.items():
        assert datagen.verbs_on(object(), entity) == sql.get(name, (i,))
        assert datagen.verbs_on(Fs(), entity) == files.get(name, (i,))
        assert datagen.verbs_on(Redpanda(), entity) == (i,)
    assert {n for n, e in by.items() if e.snapshot} == {FULL, PERIOD}


def test_mix_gives_each_table_only_its_verbs(seed):
    [txns] = _runs(seed, 1)
    got = {
        name: {k.value for k, n in per.items() if n}
        for name, per in datagen.op_counts(txns).items()
    }
    assert got == {
        FULL: {"insert", "update", "delete"},
        SOFT: {"insert", "update"},
        NO_DELETE: {"insert", "update", "delete"},
        CDC: {"insert"},
        APPEND: {"insert"},
        PERIOD: {"insert"},
        LOG: {"insert"},
    }


def test_the_same_runs_plan_the_same_changes(seed):
    def lines(runs):
        return [
            json.dumps(datagen.op_line({}, n, c), default=str)
            for txns in runs
            for n, t in enumerate(txns)
            for c in t
        ]

    assert lines(_runs(seed, 3)) == lines(_runs(seed, 3))


def test_counters_never_repeat_and_every_change_is_later(seed):
    """Across the seed and three AUTO runs: an inserted sim_counter is new,
    past the insert base; every inserted or updated data_ts (a CDC row's new
    image, the log's ts) is later than every one the table had."""
    runs = _runs(seed, 3)
    for name in TABLES:
        counters = {r["sim_counter"] for r in seed[name].rows}
        stamp = "ts" if name == LOG else "data_ts"
        col = f"@td.cdc.data.col.new.{stamp}" if name == CDC else stamp

        def when(row, col=col):
            v = row.get(col)
            return v.strftime("%Y-%m-%d %H:%M:%S") if hasattr(v, "strftime") else v

        last = max(when(r) for r in seed[name].rows if when(r))
        assert last < "2025-01-01 00:00:01"
        for txns in runs:
            stamps = []
            for c in _changes(txns, name):
                if c.kind is OpKind.INSERT:
                    sc = c.row["sim_counter"]
                    assert sc > INSERT_BASE and sc not in counters, (name, sc)
                    counters.add(sc)
                    if not (name == CDC and c.row["@td.cdc.meta.op"] == "d"):
                        stamps.append(when(c.row))
                elif c.kind is OpKind.UPDATE:
                    stamps.append(c.set_values["data_ts"])
            stamps = [s for s in stamps if s]  # a continuation line has no time
            assert stamps, name
            assert min(stamps) > last, name
            assert stamps == sorted(stamps), name
            last = max(stamps)


def test_updates_and_deletes_name_rows_that_are_there(seed):
    """Replayed on a table as SQL would hold it, three runs of every verb --
    the update and delete walks included -- touch only rows that exist."""
    runs = _runs(seed, 3, sets=6)
    for name in (FULL, SOFT, NO_DELETE):
        rows = {r["sim_counter"]: dict(r) for r in seed[name].rows}
        for txns in runs:
            _apply(rows, _changes(txns, name))


def test_versions_name_keys_that_exist(seed):
    """An insup change row is a version of a key the table has -- soft delete:
    a key not deleted -- or a new key, its tenant's next."""
    runs = _runs(seed, 3)
    for name in (SOFT, NO_DELETE):
        alive: dict = {}
        top: dict = {}
        for r in seed[name].rows:
            key = (r["tenant_id"], r["entity_id"])
            top[key[0]] = max(top.get(key[0], 0), key[1])
            if name == SOFT and r["deleted"]:
                alive.pop(key, None)
            else:
                alive[key] = alive.get(key, 0) + 1
        versions = 0
        for txns in runs:
            for c in _changes(txns, name):
                if c.kind is OpKind.DELETE:  # no_delete's physical delete
                    continue
                if c.kind is OpKind.UPDATE:
                    if c.set_values.get("deleted"):
                        row = next(
                            r
                            for r in seed[name].rows
                            if r["sim_counter"] == c.where["sim_counter"]
                        )
                        alive.pop((row["tenant_id"], row["entity_id"]))
                    continue
                key = (c.row["tenant_id"], c.row["entity_id"])
                if key in alive:
                    versions += 1
                else:
                    assert key[1] == top[key[0]] + 1, (name, key)  # a new key
                    top[key[0]] = key[1]
                if name == SOFT and c.row["deleted"]:
                    alive.pop(key)
                else:
                    alive[key] = alive.get(key, 0) + 1
        assert versions, name


# ---- R2: the CDC stream continues its contract -----------------------------


def test_the_cdc_stream_keeps_its_contract_across_runs(seed):
    def image(row, side):
        return {
            k.rsplit(".", 1)[1]: v
            for k, v in row.items()
            if k.startswith(f"@td.cdc.data.col.{side}.")
        }

    live: dict = {}
    for r in seed[CDC].rows:
        new = image(r, "new")
        key = (new["tenant_id"], new["entity_id"])
        if r["@td.cdc.meta.op"] == "d":
            live.pop(key)
        else:
            live[key] = new
    ops = set()
    for txns in _runs(seed, 4):
        rows = [c.row for c in _changes(txns, CDC)]
        for r in rows:
            op, old, new = r["@td.cdc.meta.op"], image(r, "old"), image(r, "new")
            key = (new["tenant_id"], new["entity_id"])
            ops.add(op)
            if op == "i":
                assert key not in live and set(old.values()) == {None}
                live[key] = new
            elif op == "u":
                assert old == live[key], key  # the before-image is the last new
                live[key] = new
            else:
                assert new == live.pop(key) and set(old.values()) == {None}
        tx, sq = None, 0
        sizes = []
        for r in rows:
            if r["@td.cdc.meta.tx"] == tx:
                sq += 1
                sizes[-1] += 1
            else:
                tx, sq = r["@td.cdc.meta.tx"], 1
                sizes.append(1)
            assert r["@td.cdc.meta.sq"] == sq
        assert max(sizes) <= 3
    assert ops == {"i", "u", "d"}


def test_a_run_never_changes_a_key_an_earlier_run_deleted(seed):
    """What the first run deleted, no later run updates or deletes."""
    first, *later = _runs(seed, 5)
    gone = {
        (r["@td.cdc.data.col.new.tenant_id"], r["@td.cdc.data.col.new.entity_id"])
        for r in (c.row for c in _changes(first, CDC))
        if r["@td.cdc.meta.op"] == "d"
    }
    assert gone
    for txns in later:
        for r in (c.row for c in _changes(txns, CDC)):
            key = (
                r["@td.cdc.data.col.new.tenant_id"],
                r["@td.cdc.data.col.new.entity_id"],
            )
            assert r["@td.cdc.meta.op"] == "i" or key not in gone


# ---- R4, R5: the next period, the log's next lines --------------------------


def test_an_insert_adds_the_next_period(seed):
    last = {
        (r["tenant_id"], r["entity_id"]): r
        for r in seed[PERIOD].rows
        if r["period_end"].isoformat() == "2024-12-31"
    }
    ends = []
    for txns in _runs(seed, 2):
        rows = [c.row for c in _changes(txns, PERIOD)]
        [end] = {r["period_end"] for r in rows}
        ends.append(end.isoformat())
        now = {(r["tenant_id"], r["entity_id"]): r for r in rows}
        assert len(now) == len(rows)
        kept = set(now) & set(last)
        assert kept and set(last) - set(now) and set(now) - set(last)
        payload = ("name", "status", "amount")
        assert any(any(now[k][f] != last[k][f] for f in payload) for k in kept) and any(
            all(now[k][f] == last[k][f] for f in payload) for k in kept
        )
        last = now
    assert ends == ["2025-01-31", "2025-02-28"]


def test_the_log_continues_its_lines(seed):
    [txns] = _runs(
        seed, 1, ops=OpSelector.INSERT, sets=1, entities=[LOG], rows={LOG: 30}
    )
    rows = [c.row for c in _changes(txns, LOG)]
    assert len(rows) == 30
    # line 10,024 of the log (the seed's 10,000 on) is a continuation
    continuation = [n for n, r in enumerate(rows) if r["line"].startswith("    at ")]
    assert continuation == [24]
    for r in rows:
        if r["ts"] is not None:
            assert r["line"].startswith(r["ts"].replace(" ", "T") + ".000Z")


# ---- a file domain: snapshots restaged, every table staged ------------------


@pytest.fixture
def ndjson_only(monkeypatch):
    """One format, the one the standard library reads back: the staging is
    the same for every format."""
    pytest.importorskip("polars")
    monkeypatch.setattr(emit, "FILE_FORMATS", ("ndjson",))


def _fs_domain(tmp_path, monkeypatch):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import console
    from tabsdata_dev.common.systems.systems.fs.backend import Fs

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    system = Fs()
    meta = system.domain_meta({"SYS_PATH": str(tmp_path / "root")}, "d1", "")
    path = tmp_path / "d1.desc"
    descriptor.write_domain(
        path, "fs", "d1", sys_name="fs", external_name="d1", meta=meta
    )
    descriptor.set_model(path, MODEL, datagen.entities_of(MODEL))
    return system, path, tmp_path / "root" / "d1"


def _run(module, system, path, tmp_path, verb, slug="fs", **opts):
    from tabsdata_dev.common.systems import cli

    return module.run(
        cli.Context(
            tool=constants.DOM_TOOL,
            verb=verb,
            slug=slug,
            system=system,
            args=argparse.Namespace(**opts),
            name="d1",
            info=descriptor.load(path),
            path=path,
            store_dir=tmp_path,
        )
    )


def _modify(**opts):
    args = {
        "entity": "ALL",
        "sets": 3,
        "ops": "Mix",
        "seed": "AUTO",
        "trx_mode": "serial",
        "trx_concurrency": 4,
        "dry_run": False,
        "emit_ops": None,
    }
    args.update(opts)
    return args


def _read(path):
    return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()]


def test_a_file_domain_restages_the_snapshot_as_its_state(
    tmp_path, monkeypatch, ndjson_only
):
    """Two Mix runs: the newest brz_full_snapshot file is the seed's rows with
    each run's trail applied; a period is a file of its own, the log a file of
    its lines, every other table a file of the rows inserted."""
    from tabsdata_dev.common.systems.systems._common.commands import (
        dom_create_data,
        dom_modify_data,
    )

    system, path, root = _fs_domain(tmp_path, monkeypatch)
    load = {"size": 1, "force": False, "dry_run": False, "emit_ops": None}
    assert _run(dom_create_data, system, path, tmp_path, "create-data", **load) == 0
    [seed_file] = (root / "ndjson").glob(f"{FULL}_*.ndjson")
    state = {r["sim_counter"]: r for r in _read(seed_file)}
    trail = tmp_path / "trail.jsonl"
    for run in (1, 2):
        before = set(root.rglob("*"))
        opts = _modify(emit_ops=str(trail))
        assert _run(dom_modify_data, system, path, tmp_path, "modify-data", **opts) == 0
        new = {p.relative_to(root).as_posix() for p in set(root.rglob("*")) - before}
        lines = [x for x in _read(trail) if x["seed"] == run]
        for x in lines:
            if x["entity"] != FULL:
                continue
            sc = (x.get("row") or x["key"])["sim_counter"]
            if x["op"] == "insert":
                state[sc] = x["row"]
            elif x["op"] == "update":
                state[sc].update(x["set"])
            else:
                del state[sc]
        [snap] = [p for p in new if p.startswith(f"ndjson/{FULL}_")]
        assert {r["sim_counter"]: r for r in _read(root / snap)} == state
        assert {x["op"] for x in lines if x["entity"] == FULL} == {
            "insert",
            "update",
            "delete",
        }
        # every other table: the rows its trail inserted, nothing else
        for name in (SOFT, NO_DELETE, CDC, APPEND):
            [f] = [p for p in new if p.startswith(f"ndjson/{name}_")]
            assert _read(root / f) == [
                x["row"] for x in lines if x["entity"] == name and x["op"] == "insert"
            ]
            assert {x["op"] for x in lines if x["entity"] == name} == {"insert"}
        [period] = [p for p in new if p.startswith(f"ndjson/{PERIOD}_")]
        assert _read(root / period) == [
            x["row"] for x in lines if x["entity"] == PERIOD
        ]
        [log] = [p for p in new if p.startswith(f"log/{LOG}_")]
        assert (root / log).read_bytes().decode("utf-8").splitlines() == [
            x["row"]["line"] for x in lines if x["entity"] == LOG
        ]
    info = descriptor.load(path)
    assert [c["seed"] for c in info.changes] == [1, 2]
    load["force"] = True
    assert _run(dom_create_data, system, path, tmp_path, "create-data", **load) == 0
    assert descriptor.load(path).changes == []  # a reload starts the state again


def test_each_period_is_a_file_of_its_own(tmp_path, monkeypatch, ndjson_only):
    from tabsdata_dev.common.systems.systems._common.commands import (
        dom_create_data,
        dom_modify_data,
    )

    system, path, root = _fs_domain(tmp_path, monkeypatch)
    load = {"size": 1, "force": False, "dry_run": False, "emit_ops": None}
    assert _run(dom_create_data, system, path, tmp_path, "create-data", **load) == 0
    opts = _modify(entity=PERIOD, ops="Insert", sets=2)
    assert _run(dom_modify_data, system, path, tmp_path, "modify-data", **opts) == 0
    files = sorted((root / "ndjson").glob(f"{PERIOD}_*.ndjson"))
    assert len(files) == 3  # the seed's, then one per period
    ends = [{r["period_end"] for r in _read(f)} for f in files]
    assert ends[1:] == [{"2025-01-31"}, {"2025-02-28"}]


def test_a_file_domain_refuses_an_update_but_on_a_snapshot(tmp_path, monkeypatch):
    """brz_insup_no_delete takes UPDATEs on SQL; a file domain says it does not."""
    from tabsdata_dev.common.systems.systems._common.commands import dom_modify_data

    system, path, _ = _fs_domain(tmp_path, monkeypatch)
    descriptor.record_data(path, "1", {f"csv/{NO_DELETE}_S.csv": 10_000})
    opts = _modify(entity=NO_DELETE, ops="Update", dry_run=True)
    with pytest.raises(TdxError, match="does not support update on a fs domain"):
        _run(dom_modify_data, system, path, tmp_path, "modify-data", **opts)


def test_seeded_rows_are_counted_by_entity_on_a_file_domain():
    seeded = {
        f"csv/{FULL}_20261109T101010_123.csv": 100,
        f"avro/{FULL}_20261109T101010_123.avro": 100,
        f"log/{LOG}_20261109T101010_123.log": 7,
        "departments": 9,
    }
    assert datagen.seeded_rows(seeded) == {FULL: 100, LOG: 7, "departments": 9}


# ---- --dry-run plans every table, on every nature ---------------------------


def test_a_dry_run_plans_every_table_on_sql_file_and_kafka(tmp_path, monkeypatch):
    from tabsdata_dev.common.systems.systems._common.commands import dom_modify_data
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda
    from tabsdata_dev.common.systems.systems.redpanda.domain import modify_data

    class Sql:  # a SQL system a dry run never reaches
        pass

    def planned(trail):
        return {x["entity"]: x["op"] for x in _read(trail)} if trail.exists() else {}

    system, path, _ = _fs_domain(tmp_path, monkeypatch)
    descriptor.record_data(path, "1", {f"csv/{t}_S.csv": 1 for t in TABLES})
    trail = tmp_path / "fs.jsonl"
    opts = _modify(dry_run=True, emit_ops=str(trail), sets=1)
    assert _run(dom_modify_data, system, path, tmp_path, "modify-data", **opts) == 0
    assert sorted(planned(trail)) == sorted(TABLES)

    descriptor.record_data(path, "1", {t: 10_000 for t in TABLES})
    trail = tmp_path / "sql.jsonl"
    opts = _modify(dry_run=True, emit_ops=str(trail))
    assert (
        _run(
            dom_modify_data,
            Sql(),
            path,
            tmp_path,
            "modify-data",
            slug="postgres",
            **opts,
        )
        == 0
    )
    assert sorted(planned(trail)) == sorted(TABLES)

    trail = tmp_path / "kafka.jsonl"
    opts = {
        "size": 1,
        "entity": "ALL",
        "schema_changes": None,
        "dry_run": True,
        "emit_ops": str(trail),
    }
    assert (
        _run(
            modify_data,
            Redpanda(),
            path,
            tmp_path,
            "modify-data",
            slug="redpanda",
            **opts,
        )
        == 0
    )
    assert planned(trail) == dict.fromkeys(TABLES, "insert")
    assert descriptor.load(path).changes == []  # nothing applied, nothing kept


# ---- kafka: the recipe's inserts, in the domain's message format -----------


def _rp_domain(tmp_path, monkeypatch, fmt="json"):
    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import console
    from tabsdata_dev.common.systems.systems.redpanda import wire

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    path = tmp_path / "rp"
    meta = {"DB": "pfx", "KAFKA_BROKERS": "h:9", wire.META_MESSAGE_FORMAT: fmt}
    descriptor.write_domain(
        path, "redpanda", "d1", sys_name="redpanda", external_name="pfx", meta=meta
    )
    descriptor.set_model(path, MODEL, datagen.entities_of(MODEL))
    descriptor.record_data(path, "1", {f"pfx.{t}": 10_000 for t in TABLES})
    return path


@pytest.fixture
def producer(monkeypatch):
    """A stand-in confluent_kafka whose Producer keeps what it was sent."""
    import sys
    import types

    sent: dict = {}

    class Producer:
        def __init__(self, conf):
            pass

        def produce(self, topic, value, key=None, on_delivery=None):
            sent.setdefault(topic, []).append(value)

        def poll(self, timeout):
            return 0

        def flush(self, timeout=None):
            return 0

    root = types.ModuleType("confluent_kafka")
    root.Producer = Producer
    monkeypatch.setitem(sys.modules, "confluent_kafka", root)
    return sent


def test_kafka_runs_continue_the_recipe(tmp_path, monkeypatch, producer):
    """Two runs: each topic gets the recipe's next inserts, with every column
    in the trail, and the second continues the first."""
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda
    from tabsdata_dev.common.systems.systems.redpanda.domain import modify_data

    path = _rp_domain(tmp_path, monkeypatch)
    trail = tmp_path / "ops.jsonl"
    opts = {"size": 1, "entity": "ALL", "schema_changes": None, "dry_run": False}
    opts["emit_ops"] = str(trail)
    for _ in range(2):
        assert (
            _run(
                modify_data,
                Redpanda(),
                path,
                tmp_path,
                "modify-data",
                slug="redpanda",
                **opts,
            )
            == 0
        )
    lines = _read(trail)
    assert [c["seed"] for c in descriptor.load(path).changes] == [1, 2]
    for name in TABLES:
        sent = [json.loads(v) for v in producer[f"pfx.{name}"]]
        rows = [x["row"] for x in lines if x["entity"] == name]
        assert sent == rows  # every column, as produced
        counters = [r["sim_counter"] for r in rows]
        assert counters == list(range(INSERT_BASE + 1, INSERT_BASE + 1 + len(rows)))
    periods = {x["row"]["period_end"] for x in lines if x["entity"] == PERIOD}
    assert periods == {"2025-01-31", "2025-02-28"}
    assert {x["seed"] for x in lines} == {1, 2}


@pytest.mark.parametrize("fmt", ["avro", "protobuf"])
def test_kafka_carries_bronze_as_avro_or_protobuf_but_the_cdc_table(
    tmp_path, monkeypatch, producer, capsys, fmt
):
    pytest.importorskip("fastavro")
    pytest.importorskip("google.protobuf")
    import io

    import fastavro
    from tabsdata_dev.common.systems.systems.redpanda import wire
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda
    from tabsdata_dev.common.systems.systems.redpanda.domain import modify_data

    path = _rp_domain(tmp_path, monkeypatch, fmt)
    trail = tmp_path / "ops.jsonl"
    opts = {"size": 1, "entity": "ALL", "schema_changes": None, "dry_run": False}
    opts["emit_ops"] = str(trail)
    assert (
        _run(
            modify_data,
            Redpanda(),
            path,
            tmp_path,
            "modify-data",
            slug="redpanda",
            **opts,
        )
        == 0
    )
    assert f"{CDC}: no {fmt} messages (not {fmt} names: @td.cdc.meta.op" in (
        capsys.readouterr().err
    )
    assert f"pfx.{CDC}" not in producer
    lines = _read(trail)
    assert CDC not in {x["entity"] for x in lines}  # the trail is what was sent
    assert CDC not in descriptor.load(path).changes[0]["entities"]
    columns = {e.table: e.columns for e in datagen.load_model(MODEL).entities}
    for name in (FULL, PERIOD, LOG):
        [first, *_] = producer[f"pfx.{name}"]
        row = next(x["row"] for x in lines if x["entity"] == name)
        if fmt == "avro":
            schema = fastavro.parse_schema(wire.avro_schema(name, columns[name]))
            got = fastavro.schemaless_reader(io.BytesIO(first), schema)
            assert got["sim_counter"] == row["sim_counter"]
        else:
            msg = wire.proto_class(name, columns[name])()
            msg.ParseFromString(first)
            assert msg.sim_counter == row["sim_counter"]
        if name == LOG:
            assert (got["line"] if fmt == "avro" else msg.line) == row["line"]


def test_create_model_writes_a_schema_per_table_the_format_holds(
    tmp_path, monkeypatch, capsys
):
    pytest.importorskip("google.protobuf")
    from tabsdata_dev.common.systems.systems.redpanda import wire
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda
    from tabsdata_dev.common.systems.systems.redpanda.domain import create_model

    path = _rp_domain(tmp_path, monkeypatch, "protobuf")
    descriptor.clear_model(path)
    system = Redpanda()
    monkeypatch.setattr(system, "install_schema", lambda *a, **k: None)
    out = tmp_path / "schemas"
    opts = {"model": MODEL, "force": False, "up_to_partitions": 1}
    opts["schemas_dir"] = str(out)
    assert _run(create_model, system, path, tmp_path, "create-model", **opts) == 0
    names = [t for t in TABLES if t != CDC] + [datagen.SENTINEL_ENTITY]
    assert sorted(p.name for p in out.iterdir()) == sorted(f"{n}.proto" for n in names)
    assert f"{CDC}: no protobuf messages" in capsys.readouterr().err
    assert wire.formats_of(descriptor.load(path).meta) == {}  # bronze names none


def test_the_message_format_is_the_domains_and_its_manifest_replays_it(
    tmp_path, monkeypatch
):
    from tabsdata_dev.common.systems import manifest
    from tabsdata_dev.common.systems.systems.redpanda import wire
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda

    system = Redpanda()
    sys_meta = {"HOST": "h", "PORT": "1"}
    assert system.domain_meta(sys_meta, "pfx", "")[wire.META_MESSAGE_FORMAT] == "json"
    system.use_message_format("avro")
    meta = system.domain_meta(sys_meta, "pfx", "")
    assert wire.domain_formats(meta, ["a"]) == {"a": "avro"}
    # the model's own format wins over the domain's
    meta[wire.META_MESSAGE_FORMATS] = wire.encode_formats({"a": "protobuf"})
    assert wire.domain_formats(meta, ["a", "b"]) == {"a": "protobuf", "b": "avro"}
    with system.data_plane_uri(meta) as uri:
        assert system._default_format(uri) == "avro"
    with pytest.raises(TdxError, match="--message-format takes json|avro|protobuf"):
        system.use_message_format("xml")
    path = _rp_domain(tmp_path, monkeypatch)
    info = descriptor.load(path)
    assert "message-format" not in manifest.domain_entry(info)
    info.meta[wire.META_MESSAGE_FORMAT] = "protobuf"
    assert manifest.domain_entry(info)["message-format"] == "protobuf"


def test_a_kafka_recipe_needs_the_seed(tmp_path, monkeypatch):
    from tabsdata_dev.common.systems.systems.redpanda.backend import Redpanda
    from tabsdata_dev.common.systems.systems.redpanda.domain import modify_data

    path = _rp_domain(tmp_path, monkeypatch)
    descriptor.set_model(path, MODEL, datagen.entities_of(MODEL))
    opts = {"size": 1, "entity": "ALL", "schema_changes": None, "dry_run": True}
    opts["emit_ops"] = None
    with pytest.raises(TdxError, match="run create-data first"):
        _run(
            modify_data,
            Redpanda(),
            path,
            tmp_path,
            "modify-data",
            slug="redpanda",
            **opts,
        )


def test_a_restage_without_a_plan_is_refused():
    """The model's state exists only once a plan prepared it."""
    with pytest.raises(RuntimeError, match="before prepare"):
        datagen.load_model(MODEL).restage({FULL})


# ---- reserved words ---------------------------------------------------------


def test_oracle_quotes_the_column_it_reserves_in_its_ddl_and_its_sql(seed):
    """LEVEL is ORA-03050 as a bare column name: the DDL creating the log table
    and every statement loading it have to quote it alike."""
    from tabsdata_dev.common.systems.systems.oracle.backend import Oracle

    oracle = Oracle()
    log = seed["brz_log_lines"]
    reserved = [c.name for c in log.columns if c.name in oracle.sql_reserved]
    assert reserved == ["level"]

    ddl = oracle.ddl_text(MODEL)
    assert '"level"' in ddl
    assert not [x for x in ddl.splitlines() if x.split()[:1] == ["level"]]

    kw = {"quote": oracle.sql_quote, "reserved": oracle.sql_reserved}
    [insert] = emit.iter_insert_statements(log.name, log.columns, log.rows[:1], **kw)
    assert insert.startswith('INSERT INTO brz_log_lines (sim_counter,ts,"level",')
    # A dialect that reserves nothing keeps the name bare.
    [bare] = emit.iter_insert_statements(log.name, log.columns, log.rows[:1])
    assert bare.startswith("INSERT INTO brz_log_lines (sim_counter,ts,level,")

    changes = [
        c for run in _runs(seed, 3) for txn in run for c in txn if c.table == log.name
    ]
    assert changes
    for change in changes:
        sql = datagen.render_sql(change, **kw)
        assert " level" not in sql.split(" VALUES ")[0].replace(",", " ")
