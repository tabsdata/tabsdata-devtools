#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source with a SCHEMA REGISTRY.

REGISTRY MODE IS A PROPERTY OF THE CONNECTION, NOT OF THE SOURCE. Set
`schema_registry` on `KafkaStreamSrcConn` and the consumer switches to SR-aware
serdes; the function below is otherwise byte-identical to the registry-less Avro
one in the `kafka_src` suite — same `data_format`, same `schema`, same trigger,
same fold.

WHAT CHANGES IS THE WIRE. A registry-mode message is in the CONFLUENT WIRE FORMAT:

    [0x00][4-byte big-endian schema id][payload]

The consumer reads the id, fetches THAT EXACT SCHEMA VERSION from the registry,
and decodes with it. That is what lets a topic survive a producer which evolves
its schema: old messages keep decoding under the version they were written with,
instead of being reinterpreted under the newest one.

A PLAIN MESSAGE ON A REGISTRY TOPIC FAILS TO DESERIALIZE — including everything
`rpk topic produce` writes and everything the redpanda domain's own data plane
produces, which are plain JSON. That is not a misconfiguration to debug; it is
the format doing its job. Which is why this suite consumes a topic of its own
that only a registry-aware producer writes to, and NOT the seeded
`<prefix>.employees`.

`schema` STAYS REQUIRED in registry mode: the connector cross-checks it against
the schema the registry resolves, so a drift between what you believe the topic
carries and what it actually carries is caught at decode time rather than three
transforms later.

THE TWO REGISTRY KINDS, both plain nested mappings in the connection YAML with no
kind/apiVersion/type envelope (see `connections/kafka_topic_in_registry.yaml`):

    Confluent  url [+ credentials {user, password}] [+ configs {}]
    AWS Glue   region_name, registry_name, schema_name,
               credentials {access_key_id, secret_access_key} [+ configs {}]

The redpanda domain publishes a Confluent-compatible registry and exports it as
the `SCHEMA_REGISTRY_URL` meta key, which the template interpolates PLAIN
(`${D0__SCHEMA_REGISTRY_URL}`) — an endpoint is a name, not a credential.

PRODUCING SOMETHING IT CAN READ. `rpk` cannot write the wire format, so use a
registry-aware client (`confluent_kafka` is already a dependency of the
connector):

    from confluent_kafka import SerializingProducer
    from confluent_kafka.schema_registry import SchemaRegistryClient
    from confluent_kafka.schema_registry.avro import AvroSerializer

    sr = SchemaRegistryClient({"url": "<SCHEMA_REGISTRY_URL>"})
    producer = SerializingProducer({
        "bootstrap.servers": "<KAFKA_BROKERS>",
        "value.serializer": AvroSerializer(sr, EVENT_SCHEMA),
    })
    producer.produce(topic="<prefix>.registry_events",
                     value={"event_id": 1, "kind": "click",
                            "payload": None, "occurred_at": 0})
    producer.flush()

The suite's `scripts/produce_events.py --registry` does exactly that, then sends
a few PLAIN JSON events to the same topic: those must land in
`<prefix>.registry_dead`, which the suite reads back to count them.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# The schema the producer registers and the consumer cross-checks. Keeping it
# here — rather than trusting the registry alone — is what makes drift
# detectable.
EVENT_SCHEMA = json.dumps({
    "type": "record",
    "name": "Event",
    "namespace": "com.example",
    "fields": [
        {"name": "event_id", "type": "long"},
        {"name": "kind", "type": "string"},
        {"name": "payload", "type": ["null", "string"], "default": None},
        {
            "name": "occurred_at",
            "type": {"type": "long", "logicalType": "timestamp-millis"},
        },
    ],
})


@stream_publisher(
    source=KafkaStreamSrc(
        topic="${D0__DB}.registry_events",
        data_format="avro",
        schema=EVENT_SCHEMA,
        # A DLQ matters MORE in registry mode, not less: a message written
        # WITHOUT the wire format lands here instead of failing the batch, which
        # is exactly how you find a producer that is not registry-aware.
        dlq_topic="${D0__DB}.registry_dead",
        src_cfg={
            "tabsdata.kafka.poll.max_secs": 2,
            "kafka.connect_timeout_secs": 10,
        },
    ),
    batch_max_secs=60,
    batch_max_rows=25,
    output_tables=["registry_events"],
)
def read_registry_avro(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
