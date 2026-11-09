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
    opts = {"model": "employees", "force": False, "up_to_partitions": 3}
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


class _Deleting:
    """An admin client whose deletes fail as `errors` says: topic -> the
    exception its future raises."""

    def __init__(self, errors=None):
        self.errors, self.asked = errors or {}, []

    def delete_topics(self, topics):
        self.asked.extend(topics)
        return {t: _Future(self.errors.get(t)) for t in topics}


class _Future:
    def __init__(self, error):
        self.error = error

    def result(self):
        if self.error is not None:
            raise self.error


class _KafkaError:
    def __init__(self, name):
        self._name = name

    def name(self):
        return self._name

    def __str__(self):
        return f"KafkaError{{{self._name}}}"


def _destroy(tmp_path, monkeypatch, admin, force=False):
    from tabsdata_dev.common.systems.systems._common.commands import dom_destroy
    from tabsdata_dev.common.systems.systems.redpanda import backend

    path = _domain(tmp_path, monkeypatch)
    system = backend.Redpanda()
    monkeypatch.setattr(system, "_admin_client", lambda meta: admin)
    topics = ["pfx", "pfx.employees", "pfx.salaries", "other", "pfx2.x"]
    monkeypatch.setattr(system, "_topics", lambda client: topics)
    ctx = _ctx(path, tmp_path, "destroy", system, dry_run=False, force=force)
    return path, lambda: dom_destroy.run(ctx)


def test_destroy_deletes_the_domain_topic_and_its_entities_only(tmp_path, monkeypatch):
    admin = _Deleting()
    path, destroy = _destroy(tmp_path, monkeypatch, admin)
    assert destroy() == 0
    assert admin.asked == ["pfx", "pfx.employees", "pfx.salaries"]
    assert not path.exists()


def test_destroy_names_the_topics_it_could_not_delete_and_keeps_the_domain(
    tmp_path, monkeypatch
):
    """A topic left on the broker was invisible: the domain went, its topics
    stayed, and a broker full of them refused new partitions."""
    refused = Exception(_KafkaError("POLICY_VIOLATION"))
    gone = Exception(_KafkaError("UNKNOWN_TOPIC_OR_PART"))
    admin = _Deleting({"pfx.salaries": refused, "pfx.employees": gone})
    path, destroy = _destroy(tmp_path, monkeypatch, admin)
    with pytest.raises(TdxError) as err:
        destroy()
    assert str(err.value) == (
        "kafka could not delete 1 of 3 topic(s): "
        "pfx.salaries (KafkaError{POLICY_VIOLATION})"
    )
    assert admin.asked == ["pfx", "pfx.employees", "pfx.salaries"]
    assert path.exists()


def test_a_forced_destroy_removes_the_domain_whatever_its_topics_did(
    tmp_path, monkeypatch
):
    admin = _Deleting({"pfx": Exception(_KafkaError("REQUEST_TIMED_OUT"))})
    path, destroy = _destroy(tmp_path, monkeypatch, admin, force=True)
    assert destroy() == 0
    assert not path.exists()


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
    uri = "kafka://b:1/pfx"
    assert backend.Redpanda()._produce(uri, [table]) == {"pfx.t": 2}
    assert sent == [
        ("pfx.t", b"1", {"id": 1, "name": "a"}),
        ("pfx.t", b"2", {"id": 2}),
    ]
    # a delivery the broker refused is the produce's error, never a count
    fail.append("MSG_SIZE_TOO_LARGE")
    with pytest.raises(TdxError, match="2 failed .first: MSG_SIZE_TOO_LARGE"):
        backend.Redpanda()._produce(uri, [table])


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
        opts = {"size": 1, "force": False, "dry_run": dry_run, "emit_ops": str(dest)}
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

    opts = {"size": 1, "dry_run": False, "emit_ops": None, "entity": "departments"}
    opts["schema_changes"] = None
    assert modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts)) == 0
    assert loaded[-1] == ["departments"]
    opts["entity"] = "xp_sentinel"  # never generated, so not a topic data goes to
    with pytest.raises(TdxError, match="unknown entity xp_sentinel"):
        modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts))


@pytest.mark.parametrize(
    "verb, own",
    [
        ("create", ["--sys", "s", "--registry", "on"]),
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
    if verb == "create":
        assert args.registry == "on"


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


# ---- message formats: Avro and Protobuf, plain and registry-framed ----------


def _shop_tables():
    return datagen.load_model("shopevents").build_initial(
        random.Random(datagen.INITIAL_SEED), datagen.BASE_SIZE
    )


def test_shopevents_names_its_avro_and_protobuf_entities():
    assert datagen.message_formats("shopevents") == {
        "page_view": "avro",
        "order_placed": "protobuf",
    }
    assert datagen.message_formats("employees") == {}


@pytest.mark.parametrize(
    "formats, why",
    [
        ({"nope": "avro"}, "names no entity: nope"),
        ({"a": "thrift"}, "'thrift' is not one of json, avro, protobuf"),
    ],
)
def test_a_models_message_formats_are_checked(tmp_path, monkeypatch, formats, why):
    model = tmp_path / "m"
    model.mkdir()
    (model / "entities.json").write_text(json.dumps(["a"]), encoding="utf-8")
    (model / "model.json").write_text(
        json.dumps({"message_formats": formats}), encoding="utf-8"
    )
    monkeypatch.setattr(datagen, "_models_root", lambda: tmp_path)
    with pytest.raises(TdxError, match=why):
        datagen.message_formats("m")


def test_an_avro_message_is_the_record_and_nothing_else():
    """Plain Avro: the record's binary encoding, no header, readable with the
    schema the consumer is given -- nulls, a timestamp and a boolean intact."""
    import io

    fastavro = pytest.importorskip("fastavro")
    from tabsdata_dev.common.systems.systems.redpanda import shape, wire

    views = _shop_tables()[0]
    encode = wire.encoder("avro", "pfx.page_view", "page_view", views.columns)
    schema = json.loads(wire.schema_text("avro", "page_view", views.columns))
    assert schema["name"] == "PageView" and schema["namespace"] == "tdd"
    parsed = fastavro.parse_schema(schema)
    for row in views.rows[:20]:
        sent = encode(shape.record(row, views.columns))
        assert not sent.startswith(b"Obj\x01")  # no container header
        back = fastavro.schemaless_reader(io.BytesIO(sent), parsed)
        assert back == row


def test_a_protobuf_message_decodes_with_the_declared_message():
    """Plain Protobuf: SerializeToString of tdd.OrderPlaced; a null is absent,
    a decimal its text at the column's scale, a date and a time ISO 8601."""
    pytest.importorskip("google.protobuf")
    from tabsdata_dev.common.systems.systems.redpanda import shape, wire

    orders = _shop_tables()[1]
    encode = wire.encoder(
        "protobuf", "pfx.order_placed", "order_placed", orders.columns
    )
    cls = wire.proto_class("order_placed", orders.columns)
    assert cls.DESCRIPTOR.full_name == "tdd.OrderPlaced"
    nulls = 0
    for row in orders.rows:
        msg = cls()
        msg.ParseFromString(encode(shape.record(row, orders.columns)))
        assert msg.order_id == row["order_id"] and msg.items == row["items"]
        assert msg.total == f"{row['total']:.2f}"
        assert msg.placed_at == row["placed_at"].isoformat()
        assert msg.ship_by == row["ship_by"].isoformat()
        if row["coupon"] is None:
            nulls += 1
            assert not msg.HasField("coupon")
        else:
            assert msg.coupon == row["coupon"]
    assert nulls  # the model has null coupons, so absence was exercised


def test_the_proto_text_declares_what_the_descriptor_holds():
    """The descriptor is built, not compiled from the text (no protoc), so the
    two are compared field by field -- name, number, type and optional. That
    protoc compiles the text to this very descriptor is in VERIFIED.md."""
    import re

    pytest.importorskip("google.protobuf")
    from google.protobuf import descriptor_pb2
    from tabsdata_dev.common.systems.systems.redpanda import wire

    fdp = descriptor_pb2.FieldDescriptorProto
    names = {
        fdp.TYPE_INT32: "int32",
        fdp.TYPE_INT64: "int64",
        fdp.TYPE_BOOL: "bool",
        fdp.TYPE_DOUBLE: "double",
        fdp.TYPE_STRING: "string",
    }
    for table in _shop_tables():
        text = wire.proto_text(table.name, table.columns)
        declared = re.findall(
            r"^  (optional )?(\w+) (\w+) = (\d+);$", text, re.MULTILINE
        )
        msg = wire.proto_descriptor(table.name, table.columns).message_type[0]
        assert f"message {msg.name} {{" in text and "package tdd;" in text
        built = [
            (
                "optional " if f.proto3_optional else "",
                names[f.type],
                f.name,
                str(f.number),
            )
            for f in msg.field
        ]
        assert declared == built


def test_a_registry_message_carries_the_schema_id(monkeypatch):
    """Registry-framed: 0x00, the id big-endian, the message index for
    Protobuf, then the plain payload; each schema registered under
    <topic>-value as its type."""
    pytest.importorskip("fastavro")
    pytest.importorskip("google.protobuf")
    from tabsdata_dev.common.systems.systems.redpanda import shape, wire

    registered = []

    def register(registry, topic, fmt, schema):
        registered.append((registry, wire.subject(topic), fmt))
        return 258

    monkeypatch.setattr(wire, "register", register)
    for table in _shop_tables():
        fmt = datagen.message_formats("shopevents")[table.name]
        record = shape.record(table.rows[0], table.columns)
        plain = wire.encoder(fmt, f"pfx.{table.name}", table.name, table.columns)
        framed = wire.encoder(
            fmt, f"pfx.{table.name}", table.name, table.columns, "http://r:1"
        )
        head = b"\x00\x00\x00\x01\x02" + (b"\x00" if fmt == "protobuf" else b"")
        assert framed(record) == head + plain(record)
    assert registered == [
        ("http://r:1", "pfx.page_view-value", "avro"),
        ("http://r:1", "pfx.order_placed-value", "protobuf"),
    ]
    # JSON is never framed, registry or not
    assert wire.encoder("json", "pfx.t", "t", [], "http://r:1")({"a": 1}) == b'{"a":1}'


@pytest.fixture
def registry():
    """A schema registry on 127.0.0.1, port 0: what it was sent, and subjects
    to list."""
    import http.server
    import threading

    state = {"calls": [], "subjects": []}

    class Handler(http.server.BaseHTTPRequestHandler):
        def _reply(self, code, body):
            data = json.dumps(body).encode()
            self.send_response(code)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_POST(self):
            size = int(self.headers["Content-Length"])
            body = json.loads(self.rfile.read(size))
            state["calls"].append(("POST", self.path, body))
            self._reply(200, {"id": 7})

        def do_GET(self):
            state["calls"].append(("GET", self.path, None))
            self._reply(200, state["subjects"])

        def do_DELETE(self):
            state["calls"].append(("DELETE", self.path, None))
            gone = "permanent" in self.path and "gone" in self.path
            self._reply(404 if gone else 200, [1])

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    state["url"] = f"http://127.0.0.1:{server.server_address[1]}"
    yield state
    server.shutdown()
    server.server_close()


def test_the_registry_client_registers_and_deletes_a_prefixs_subjects(registry):
    from tabsdata_dev.common.systems.systems.redpanda import wire

    assert wire.register(registry["url"], "pfx.t", "protobuf", "syntax") == 7
    assert registry["calls"][0] == (
        "POST",
        "/subjects/pfx.t-value/versions",
        {"schema": "syntax", "schemaType": "PROTOBUF"},
    )
    registry["calls"].clear()
    registry["subjects"] = ["pfx.a-value", "pfx.gone-value", "other.a-value", "pfx"]
    assert wire.delete_subjects(registry["url"], "pfx") == []
    assert [c[1] for c in registry["calls"]] == [
        "/subjects",
        "/subjects/pfx.a-value",
        "/subjects/pfx.a-value?permanent=true",
        "/subjects/pfx.gone-value",
        "/subjects/pfx.gone-value?permanent=true",  # 404: already gone
    ]


def test_the_handle_carries_the_formats_and_registry(kafka):
    """data_plane_uri puts the recorded formats and, with --registry on, the
    registry URL in the handle's query; the endpoint ignores it."""
    from tabsdata_dev.common.systems.systems.redpanda import backend, wire

    system = backend.Redpanda()
    meta = {"KAFKA_BROKERS": "h:9", "DB": "pfx", "SCHEMA_REGISTRY_URL": "http://h:8"}
    meta[wire.META_MESSAGE_FORMATS] = wire.encode_formats({"a": "avro"})
    with system.data_plane_uri(meta) as uri:
        assert system._wire(uri) == ({"a": "avro"}, "")
        assert system._endpoint(uri)[1:] == ("h:9", "pfx")
    meta[wire.META_REGISTRY] = wire.REGISTRY_ON
    with system.data_plane_uri(meta) as uri:
        assert system._wire(uri) == ({"a": "avro"}, "http://h:8")
    plain = {"KAFKA_BROKERS": "h:9", "DB": "pfx"}
    with system.data_plane_uri(plain) as uri:
        assert uri == "kafka://h:9/pfx" and system._wire(uri) == ({}, "")


def test_produce_encodes_each_topic_in_its_format(kafka):
    pytest.importorskip("fastavro")
    pytest.importorskip("google.protobuf")
    from tabsdata_dev.common.systems import emit
    from tabsdata_dev.common.systems.systems.redpanda import backend, wire

    sent = {}

    class Producer:
        def __init__(self, conf):
            pass

        def produce(self, topic, value, key=None, on_delivery=None):
            sent.setdefault(topic, []).append(value)

        def poll(self, timeout):
            return 0

        def flush(self, timeout=None):
            return 0

    kafka.Producer = Producer
    tables = _shop_tables()
    tables.append(emit.Table("plain", tables[0].columns[:1], [{"view_id": 5}]))
    formats = wire.encode_formats(datagen.message_formats("shopevents"))
    meta = {"KAFKA_BROKERS": "h:9", "DB": "pfx", wire.META_MESSAGE_FORMATS: formats}
    system = backend.Redpanda()
    with system.data_plane_uri(meta) as uri:
        counts = system.load_tables(uri, tables)
    assert counts == {"pfx.page_view": 100, "pfx.order_placed": 10, "pfx.plain": 1}
    assert sent["pfx.plain"] == [b'{"view_id":5}']
    cls = wire.proto_class("order_placed", tables[1].columns)
    msg = cls()
    msg.ParseFromString(sent["pfx.order_placed"][0])
    assert msg.order_id == 1


def test_create_model_records_the_formats_and_writes_the_schemas(
    tmp_path, monkeypatch, kafka
):
    pytest.importorskip("fastavro")
    pytest.importorskip("google.protobuf")
    from tabsdata_dev.common.systems import descriptor
    from tabsdata_dev.common.systems.systems.redpanda import backend, wire
    from tabsdata_dev.common.systems.systems.redpanda.domain import create_model

    path = _domain(tmp_path, monkeypatch, model=None)
    system = backend.Redpanda()
    monkeypatch.setattr(system, "install_schema", lambda *a, **k: None)
    out = tmp_path / "schemas"
    opts = {"model": "shopevents", "force": False, "up_to_partitions": 1}
    opts["schemas_dir"] = str(out)
    assert create_model.run(_ctx(path, tmp_path, "create-model", system, **opts)) == 0
    assert wire.formats_of(descriptor.load(path).meta) == {
        "page_view": "avro",
        "order_placed": "protobuf",
    }
    assert sorted(p.name for p in out.iterdir()) == [
        "order_placed.proto",
        "page_view.avsc",
    ]
    assert "message OrderPlaced {" in (out / "order_placed.proto").read_text(
        encoding="utf-8"
    )
    avsc = json.loads((out / "page_view.avsc").read_text(encoding="utf-8"))
    assert [f["name"] for f in avsc["fields"]][:2] == ["view_id", "session_id"]


def test_schema_changes_are_refused_on_schema_bound_topics(tmp_path, monkeypatch):
    from tabsdata_dev.common.systems import descriptor
    from tabsdata_dev.common.systems.systems.redpanda import backend, wire
    from tabsdata_dev.common.systems.systems.redpanda.domain import modify_data

    path = _domain(tmp_path, monkeypatch, model="shopevents")
    info = descriptor.load(path)
    info.meta[wire.META_MESSAGE_FORMATS] = wire.encode_formats(
        datagen.message_formats("shopevents")
    )
    descriptor.save(info, path)
    system = backend.Redpanda()
    loaded = []
    monkeypatch.setattr(
        system,
        "load_tables",
        lambda uri, tables: loaded.append(1) or {f"pfx.{t.name}": 1 for t in tables},
    )
    opts = {"size": 1, "dry_run": False, "emit_ops": None, "entity": "ALL"}
    opts["schema_changes"] = "add"
    with pytest.raises(
        TdxError, match=r"page_view \(avro\), order_placed \(protobuf\)"
    ):
        modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts))
    assert not loaded
    opts["schema_changes"] = None
    assert modify_data.run(_ctx(path, tmp_path, "modify-data", system, **opts)) == 0


def test_a_registry_domain_records_it_and_its_manifest_replays_it(
    tmp_path, monkeypatch
):
    from tabsdata_dev.common.systems import descriptor, manifest
    from tabsdata_dev.common.systems.systems.redpanda import backend, wire

    system = backend.Redpanda()
    sys_meta = {"HOST": "h", "PORT": "1", "SCHEMA_REGISTRY_URL": "http://h:2"}
    assert system.domain_meta(sys_meta, "pfx", "")[wire.META_REGISTRY] == "off"
    system.use_registry("on")
    meta = system.domain_meta(sys_meta, "pfx", "")
    assert wire.registry_of(meta) == "http://h:2"
    with pytest.raises(TdxError, match="--registry takes on or off"):
        system.use_registry("yes")
    path = _domain(tmp_path, monkeypatch, model=None)
    info = descriptor.load(path)
    assert "registry" not in manifest.domain_entry(info)
    info.meta[wire.META_REGISTRY] = meta[wire.META_REGISTRY]
    assert manifest.domain_entry(info)["registry"] == "on"
