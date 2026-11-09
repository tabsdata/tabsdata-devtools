#
# Copyright 2026 Tabsdata Inc.
#
"""Produce events to a redpanda domain's topic in a wire format the domain's
own data plane does not write, and append them to the trail a check reads.

    produce_events.py DOMAIN TOPIC --format json|avro|protobuf [--registry]
                      [--count N] [--first K] [--plain N] --emit-ops FILE

The domain's data plane writes a model's rows, as JSON or -- for a model that
names them, ``shopevents`` -- as Avro or Protobuf; the publishers here read one
event shape in every format, with plain messages mixed into a registry topic,
which no model's rows are, and this is what writes it.
TOPIC is the entity part: the messages go to ``<prefix>.TOPIC``, the prefix
and brokers (and the SASL user, the schema registry) read from ``tdd domain
info --format export``.

Event i (from ``--first``, default 1) is ``{event_id, kind, payload,
occurred_at}``, the shape every event publisher in functions/kafka_src and
functions/kafka_registry reads -- their schemas are repeated here, so a drift
between the two is a decode failure the check reports:

    json      the event as JSON
    avro      Avro binary, no header (what a registry-less avro source reads)
    protobuf  the com.example.UserEvent message
    --registry  Avro in the Confluent wire format, the schema registered under
              ``<topic>-value`` (what a source with a schema_registry reads)

``--plain N`` adds N plain JSON events after them -- on a registry topic,
messages its consumer must refuse to the dead-letter topic.

Each event is one insert line in ``--emit-ops`` FILE, ``entity`` TOPIC and
``row`` the event as the consumer decodes it: ``occurred_at`` an ISO UTC time
for Avro (timestamp-millis), the milliseconds otherwise. Nothing in an event is
a type's default: proto3 leaves a default out of the decoded message.
"""

from __future__ import annotations

import argparse
import json
import os
import shlex
import sys
from datetime import datetime, timezone

from tdd import note, tdd  # on the path: xp runs a python step with it

# 2026-01-01T00:00:00Z, one second per event.
_EPOCH_MS = 1767225600000
_KINDS = ("click", "view", "buy")

EVENT_AVRO = {
    "type": "record",
    "name": "Event",
    "namespace": "com.example",
    "fields": [
        {"name": "event_id", "type": "long"},
        {"name": "kind", "type": "string"},
        {"name": "payload", "type": ["null", "string"], "default": None},
        {"name": "occurred_at", "type": {"type": "long", "logicalType": "timestamp-millis"}},
    ],
}


def domain_meta(domain: str) -> dict[str, str]:
    """The domain's meta, as `info --format export` prints it."""
    meta = {}
    for line in tdd("domain", "info", "--domain", domain, "--format", "export").splitlines():
        if line.startswith("export "):
            key, _, value = line[len("export "):].partition("=")
            meta[key] = shlex.split(value)[0] if value else ""
    return meta


def events(first: int, count: int) -> list[dict]:
    return [
        {
            "event_id": i,
            "kind": _KINDS[i % len(_KINDS)],
            "payload": f"payload-{i}",
            "occurred_at": _EPOCH_MS + i * 1000,
        }
        for i in range(first, first + count)
    ]


def proto_class():
    """com.example.UserEvent, built from its descriptor -- no protoc."""
    from google.protobuf import descriptor_pb2, descriptor_pool, message_factory

    f = descriptor_pb2.FileDescriptorProto(name="user_event.proto", package="com.example", syntax="proto3")
    m = f.message_type.add(name="UserEvent")
    T = descriptor_pb2.FieldDescriptorProto
    for number, (name, kind) in enumerate(
        [("event_id", T.TYPE_INT64), ("kind", T.TYPE_STRING), ("payload", T.TYPE_STRING), ("occurred_at", T.TYPE_INT64)],
        start=1,
    ):
        m.field.add(name=name, number=number, type=kind, label=T.LABEL_OPTIONAL)
    pool = descriptor_pool.DescriptorPool()
    pool.Add(f)
    return message_factory.GetMessageClass(pool.FindMessageTypeByName("com.example.UserEvent"))


def encoder(fmt: str, registry: bool, meta: dict, topic: str):
    if registry:
        from confluent_kafka.schema_registry import SchemaRegistryClient
        from confluent_kafka.schema_registry.avro import AvroSerializer
        from confluent_kafka.serialization import MessageField, SerializationContext

        sr = SchemaRegistryClient({"url": meta["SCHEMA_REGISTRY_URL"]})
        serialize = AvroSerializer(sr, json.dumps(EVENT_AVRO))
        ctx = SerializationContext(topic, MessageField.VALUE)
        return lambda e: serialize(e, ctx)
    if fmt == "avro":
        import io

        import fastavro

        schema = fastavro.parse_schema(EVENT_AVRO)

        def avro(e):
            buf = io.BytesIO()
            fastavro.schemaless_writer(buf, schema, e)
            return buf.getvalue()

        return avro
    if fmt == "protobuf":
        cls = proto_class()
        return lambda e: cls(**e).SerializeToString()
    return lambda e: json.dumps(e, separators=(",", ":")).encode()


def decoded(e: dict, fmt: str, registry: bool) -> dict:
    """The event as the consumer hands it on: Avro decodes timestamp-millis."""
    if fmt == "avro" or registry:
        at = datetime.fromtimestamp(e["occurred_at"] / 1000, tz=timezone.utc)
        return {**e, "occurred_at": at.isoformat()}
    return dict(e)


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument("domain")
    p.add_argument("topic")
    p.add_argument("--format", choices=("json", "avro", "protobuf"), required=True)
    p.add_argument("--registry", action="store_true")
    p.add_argument("--count", type=int, default=50)
    p.add_argument("--first", type=int, default=1)
    p.add_argument("--plain", type=int, default=0)
    p.add_argument("--emit-ops", required=True)
    a = p.parse_args()
    if a.registry and a.format != "avro":
        p.error("--registry is Avro in the Confluent wire format: --format avro")
    if a.first < 1:
        p.error("--first must be >= 1: an event_id of 0 is a default proto3 leaves out")

    from confluent_kafka import Producer

    meta = domain_meta(a.domain)
    topic = f"{meta['DB']}.{a.topic}"
    conf = {"bootstrap.servers": meta["KAFKA_BROKERS"]}
    if meta.get("USER"):
        conf |= {
            "security.protocol": "SASL_PLAINTEXT",
            "sasl.mechanism": meta.get("SASL_MECHANISM") or "SCRAM-SHA-256",
            "sasl.username": meta["USER"],
            "sasl.password": meta["PASSWORD"],
        }
    producer = Producer(conf)
    encode = encoder(a.format, a.registry, meta, topic)
    sent = [(e, encode(e), decoded(e, a.format, a.registry)) for e in events(a.first, a.count)]
    plain = encoder("json", False, meta, topic)
    sent += [(e, plain(e), dict(e)) for e in events(a.first + a.count, a.plain)]
    for e, value, _ in sent:
        producer.produce(topic, value, key=str(e["event_id"]).encode())
        producer.poll(0)
    left = producer.flush(30)
    if left:
        sys.exit(f"{left} message(s) not delivered to {topic}")

    stamp = datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0).isoformat()
    run = {"ts": stamp, "domain": a.domain, "verb": "produce-events", "dry_run": False, "txn": 0}
    text = "".join(
        json.dumps({**run, "op": "insert", "entity": a.topic, "row": row}) + "\n" for _, _, row in sent
    )
    # One append, as tdd domain's own --emit-ops writes: steps sharing the file
    # never interleave inside one run's lines.
    fd = os.open(a.emit_ops, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
    try:
        os.write(fd, text.encode())
    finally:
        os.close(fd)
    how = "registry avro" if a.registry else a.format
    note(f"{a.count} {how} + {a.plain} plain to {a.topic}" if a.plain else f"{a.count} {how} to {a.topic}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
