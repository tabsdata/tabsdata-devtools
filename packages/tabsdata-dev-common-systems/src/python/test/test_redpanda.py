#
# Copyright 2026 Tabsdata Inc.
#

"""redpanda's own verbs and data plane: partitions, the topics a run writes,
schema variances and the messages produced -- no broker, a fake admin client
and producer where one would be reached."""

import argparse
import json
import random

import pytest

from tabsdata_dev.common.systems import constants, datagen, dispatch
from tabsdata_dev.common.systems.errors import TdxError


def _domain(tmp_path, monkeypatch, model="employees"):
    """A redpanda domain descriptor, `model` installed and no data."""
    from tabsdata_dev.common.core import render
    from tabsdata_dev.common.systems import console, descriptor

    console.bind(render.Renderer(constants.DOM_TOOL))
    monkeypatch.setenv("_TDD_CRYPTO_KEY", "a-test-secret-long-enough")
    path = tmp_path / "rp"
    descriptor.write_domain(
        path,
        "redpanda",
        "rp",
        sys_name="redpanda",
        external_name="pfx",
        meta={"DB": "pfx", "HOST": "localhost", "PORT": "1"},
    )
    if model:
        descriptor.set_model(path, model, datagen.entities_of(model))
    return path


def _ctx(path, tmp_path, verb, system, **opts):
    from tabsdata_dev.common.systems import cli, descriptor

    return cli.Context(
        tool=constants.DOM_TOOL,
        verb=verb,
        slug="redpanda",
        system=system,
        args=argparse.Namespace(**opts),
        name="rp",
        info=descriptor.load(path),
        path=path,
        store_dir=tmp_path,
    )


def _lines(f):
    return [json.loads(x) for x in f.read_text().splitlines()]


@pytest.fixture
def kafka(monkeypatch):
    """A stand-in `confluent_kafka`: these tests run in toolsets without the
    driver too. `NewTopic` keeps what it was given; `Producer` is the test's to
    set."""
    import sys
    import types

    class NewTopic:
        def __init__(self, topic, num_partitions=1, replication_factor=1):
            self.topic, self.num_partitions = topic, num_partitions

    root = types.ModuleType("confluent_kafka")
    admin = types.ModuleType("confluent_kafka.admin")
    admin.NewTopic = NewTopic
    root.admin = admin
    monkeypatch.setitem(sys.modules, "confluent_kafka", root)
    monkeypatch.setitem(sys.modules, "confluent_kafka.admin", admin)
    return root


def test_topics_differ_in_partitions_up_to_the_most_asked():
    from tabsdata_dev.common.systems.systems.redpanda import shape

    entities = datagen.entities_of("employees")
    counts = shape.plan_partitions(entities, 4)
    assert list(counts) == entities
    assert list(counts.values()) == [1, 2, 3, 4, 1, 2, 3]
    assert set(shape.plan_partitions(entities, 1).values()) == {1}
    with pytest.raises(TdxError, match="--up-to-partitions must be >= 1"):
        shape.plan_partitions(entities, 0)
    assert shape.partitions_of({}) == {}
    meta = {shape.META_PARTITIONS: shape.encode_partitions(counts)}
    assert shape.partitions_of(meta) == counts


def test_schema_changes_vary_rows_in_turn_and_leave_the_model_alone():
    """Row j is left alone at j mod (k+1) == 0 and takes the kinds in order
    after it: add an xp_extra field, drop the last, retype the first."""
    from tabsdata_dev.common.systems.systems.redpanda import shape

    tables = datagen.load_model("employees").build_initial(random.Random(42), 100)
    original = [dict(r) for r in tables[1].rows[:5]]
    [emp] = shape.vary_tables(
        shape.select_tables(tables, "employees"), shape.parse_kinds("ALL")
    )
    sent = [shape.record(r, emp.columns) for r in emp.rows[:5]]
    assert sent[0] == original[0] and sent[4] == original[4]
    assert sent[1] == {**original[1], "xp_extra": "extra-1"}
    assert "hire_date" not in sent[2] and len(sent[2]) == 5
    assert sent[3]["emp_no"] == str(original[3]["emp_no"])
    assert tables[1].rows[:5] == original  # the model's rows are not touched
    assert emp.columns[-1].name == "xp_extra"
    # a number retyped as its string keeps its key, so its partition
    assert shape.message_key(emp.rows[3], emp.columns) == shape.message_key(
        tables[1].rows[3], tables[1].columns
    )
    [dept] = shape.vary_tables(
        shape.select_tables(tables, "departments"), shape.parse_kinds("retype")
    )
    assert dept.rows[1]["dept_no"] == ["d002"] and dept.rows[2] == tables[0].rows[2]
    assert shape.parse_kinds(None) == ()
    assert shape.parse_kinds("retype,ADD") == ("add", "retype")
    with pytest.raises(TdxError, match="not a kind: swap"):
        shape.parse_kinds("add,swap")
    with pytest.raises(TdxError, match="unknown entity nope .*produces: departments"):
        shape.select_tables(tables, "employees,nope")


def test_create_model_creates_every_topic_with_its_partitions(
    tmp_path, monkeypatch, kafka
):
    """The topics exist once the model is in, each with its partitions, and the
    counts are kept for a reload; a refused create-model records nothing."""
    from tabsdata_dev.common.systems import descriptor
    from tabsdata_dev.common.systems.systems.redpanda import backend, shape
    from tabsdata_dev.common.systems.systems.redpanda.domain import create_model

    path = _domain(tmp_path, monkeypatch, model=None)
    created = []

    class Done:
        def result(self):
            return None

    class Admin:
        def create_topics(self, topics):
            created.extend(topics)
            return {t.topic: Done() for t in topics}

    system = backend.Redpanda()
    monkeypatch.setattr(system, "_admin_client", lambda meta: Admin())
    monkeypatch.setattr(system, "_topics", lambda client: ["pfx", "pfx.departments"])
    opts = dict(model="employees", force=False, up_to_partitions=3)
    assert create_model.run(_ctx(path, tmp_path, "create-model", system, **opts)) == 0
    # departments was there already; every other entity's topic is created
    assert {t.topic: t.num_partitions for t in created} == {
        "pfx.employees": 2,
        "pfx.dept_emp": 3,
        "pfx.dept_manager": 1,
        "pfx.titles": 2,
        "pfx.salaries": 3,
        "pfx.xp_sentinel": 1,
    }
    info = descriptor.load(path)
    assert info.model == "employees"
    assert shape.partitions_of(info.meta)["dept_emp"] == 3
    opts["up_to_partitions"] = 5
    with pytest.raises(TdxError, match="already has model"):
        create_model.run(_ctx(path, tmp_path, "create-model", system, **opts))
    assert shape.partitions_of(descriptor.load(path).meta)["dept_emp"] == 3


def test_messages_are_keyed_and_carry_the_fields_a_row_has(kafka):
    from tabsdata_dev.common.systems import emit
    from tabsdata_dev.common.systems.systems.redpanda import backend

    sent = []
    full = [1]  # the first produce finds the queue full
    fail = []

    class Producer:
        def __init__(self, conf):
            self.pending = []

        def produce(self, topic, value, key=None, on_delivery=None):
            if full and full.pop():
                raise BufferError("queue full")
            sent.append((topic, key, json.loads(value)))
            self.pending.append(on_delivery)

        def poll(self, timeout):
            for cb in self.pending:
                cb(fail[0] if fail else None, None)
            self.pending = []
            return 0

        def flush(self, timeout=None):
            self.poll(0)
            return 0

    kafka.Producer = Producer
    cols = [emit.Column("id", "int"), emit.Column("name", "varchar(9)")]
    table = emit.Table("t", cols, [{"id": 1, "name": "a"}, {"id": 2}])
    conf = backend.client_conf("b:1")
    assert backend.Redpanda()._produce(conf, "pfx", [table]) == {"pfx.t": 2}
    assert sent == [
        ("pfx.t", b"1", {"id": 1, "name": "a"}),
        ("pfx.t", b"2", {"id": 2}),
    ]
    # a delivery the broker refused is the produce's error, never a count
    fail.append("MSG_SIZE_TOO_LARGE")
    with pytest.raises(TdxError, match="2 failed .first: MSG_SIZE_TOO_LARGE"):
        backend.Redpanda()._produce(conf, "pfx", [table])


def test_data_goes_to_the_entities_named_and_the_trail_is_what_was_sent(
    tmp_path, monkeypatch
):
    """--entity limits create-data and modify-data to those topics; with
    --schema-changes the --emit-ops trail holds the varied rows, a dry run's
    the same as a real one's."""
    from tabsdata_dev.common.systems import descriptor
    from tabsdata_dev.common.systems.systems.redpanda import backend
    from tabsdata_dev.common.systems.systems.redpanda.domain import (
        create_data,
        modify_data,
    )

    path = _domain(tmp_path, monkeypatch)
    loaded = []
    system = backend.Redpanda()

    def load_tables(uri, tables):
        loaded.append([t.name for t in tables])
        return {f"pfx.{t.name}": len(t.rows) for t in tables}

    monkeypatch.setattr(system, "load_tables", load_tables)
    monkeypatch.setattr(system, "install_schema", lambda *a, **k: None)

    dry, real = tmp_path / "dry.jsonl", tmp_path / "real.jsonl"
    for dry_run, dest in ((True, dry), (False, real)):
        opts = dict(size=1, force=False, dry_run=dry_run, emit_ops=str(dest))
        opts.update(entity="employees,dept_emp", schema_changes="add,drop")
        assert create_data.run(_ctx(path, tmp_path, "create-data", system, **opts)) == 0
    assert loaded == [["employees", "dept_emp"]]

    def untimed(f):
        return [
            # a run's own: its time, its id, whether it was a dry one
            {k: v for k, v in r.items() if k not in ("ts", "run", "dry_run")}
            for r in _lines(f)
        ]

    assert untimed(dry) == untimed(real)
    assert {r["entity"] for r in _lines(real)} == {"employees", "dept_emp"}
    emp = [r["row"] for r in _lines(real) if r["entity"] == "employees"]
    assert "xp_extra" not in emp[0] and emp[1]["xp_extra"] == "extra-1"
    assert "hire_date" not in emp[2] and "hire_date" in emp[3]
    assert descriptor.load(path).entities["pfx.employees"] == 100

    opts = dict(size=1, dry_run=False, emit_ops=None, entity="departments")
    opts["schema_changes"] = None
    assert modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts)) == 0
    assert loaded[-1] == ["departments"]
    opts["entity"] = "xp_sentinel"  # never generated, so not a topic data goes to
    with pytest.raises(TdxError, match="unknown entity xp_sentinel"):
        modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts))


@pytest.mark.parametrize(
    "verb, own",
    [
        ("create-model", ["--model", "employees", "--up-to-partitions", "2"]),
        ("create-data", ["--entity", "a,b", "--schema-changes"]),
        ("modify-data", ["--entity", "a", "--schema-changes", "drop"]),
    ],
)
@pytest.mark.parametrize("slug", ["redpanda", "redpandasasl"])
def test_the_dispatcher_resolves_redpandas_own_verbs(slug, verb, own):
    """redpanda's create-model, create-data and modify-data are its own, with
    the shared options and theirs; redpandasasl gets the same three, since the
    dispatcher finds commands by slug and would otherwise hand it the shared."""
    module = dispatch._command_module(constants.DOM_TOOL, slug, verb)
    assert module.__name__.endswith(f"{slug}.domain.{verb.replace('-', '_')}")
    assert module.run.__module__.endswith(f"redpanda.domain.{verb.replace('-', '_')}")
    parser = argparse.ArgumentParser()
    module.add_arguments(parser)
    args = parser.parse_args(["--domain", "d", *own])
    assert args.domain == "d"
    if verb == "create-data":
        assert args.schema_changes == constants.ENTITY_ALL and args.size == 1
    if verb == "modify-data":
        assert args.schema_changes == "drop"


def test_sasl_on_gives_the_system_a_user_its_domains_and_clients_carry(monkeypatch):
    """--sasl on: one user with a generated password, in the descriptor and in
    every domain made from it; every client config then authenticates, and the
    data-plane handle carries the credentials whatever their characters."""
    from tabsdata_dev.common.systems.systems.redpanda import backend

    system = backend.Redpanda()
    system.use_ports([29901, 29902, 29903, 29904])
    off = system.plan_system("rp", {"SASL": "off"})
    assert off["SASL"] == "off" and off["USER"] == "" and off["PASSWORD"] == ""
    on = system.plan_system("rp", {"SASL": "ON"})
    assert on["SASL"] == "on" and on["USER"] == backend.SASL_USER
    assert len(on["PASSWORD"]) >= 16 and on["SASL_MECHANISM"] == "SCRAM-SHA-256"
    with pytest.raises(TdxError, match="--sasl must be on or off"):
        system.plan_system("rp", {"SASL": "maybe"})
    assert system.synth_default("SASL", "rp") == "off"

    dom = system.domain_meta(on, "pfx", "")
    assert (dom["USER"], dom["PASSWORD"]) == (on["USER"], on["PASSWORD"])
    assert backend.client_conf("b:1") == {"bootstrap.servers": "b:1"}
    conf = backend.client_conf("b:1", "u", "p")
    assert conf["security.protocol"] == "SASL_PLAINTEXT"
    assert (conf["sasl.username"], conf["sasl.password"]) == ("u", "p")

    meta = {"KAFKA_BROKERS": "h:1", "DB": "pfx", "USER": "tdd", "PASSWORD": "a:b@c/d%e"}
    with system.data_plane_uri(meta) as uri:
        conf, brokers, prefix = system._endpoint(uri)
    assert (brokers, prefix, conf["sasl.password"]) == ("h:1", "pfx", "a:b@c/d%e")
    with system.data_plane_uri({"KAFKA_BROKERS": "h:1", "DB": "pfx"}) as uri:
        assert system._endpoint(uri) == ({"bootstrap.servers": "h:1"}, "h:1", "pfx")


def test_the_redpandasasl_type_is_redpanda_with_sasl_forced_on():
    from tabsdata_dev.common.systems.systems.redpanda import backend
    from tabsdata_dev.common.systems.systems.redpandasasl import Redpandasasl

    system = Redpandasasl()
    system.use_ports([29905, 29906])
    assert [o.name for o in system.options()] == ["PORT"]
    meta = system.plan_system("rps", {"PORT": "29905"})
    assert meta["SASL"] == "on" and meta["USER"] == backend.SASL_USER
    assert meta["PORT"] == "29905" and system.slug == "redpandasasl"


def test_a_sasl_systems_probe_authenticates(monkeypatch):
    from tabsdata_dev.common.systems import shell
    from tabsdata_dev.common.systems.systems.redpanda import backend

    calls = []
    monkeypatch.setattr(
        shell, "docker_exec_check", lambda c, *argv: calls.append(argv) or True
    )
    system = backend.Redpanda()
    assert system.check_ready("c", "") and system.check_ready("c", "pw")
    assert calls[0] == ("rpk", "cluster", "info")
    assert "user=tdd" in calls[1] and "pass=pw" in calls[1]
