#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: AVRO payloads, with a SIZE trigger.

WHY AVRO OVER JSON on a busy topic: it is self-describing and strongly typed, so
a `long` stays a long and a `logicalType` survives the decode — where JSON gives
you strings and inference. It is also far smaller on the wire.

`tabsdata.kafka.trigger.max_bytes` stages the batch once its files, plus what
is still buffered, reach N bytes. That is the natural axis for a high-volume
topic, where what you care about is the SIZE of what lands downstream rather
than its row count — a million tiny parquet files is its own kind of outage.

NOTHING PRODUCES TO THIS TOPIC in this suite, deliberately. An unknown topic is
NOT fatal: the poll loop logs it and keeps going until the topic appears, so the
configuration is documented without needing an Avro encoder in the harness. To
feed it, produce with a registry-aware client — see the `kafka_registry` suite,
whose docstring has a `confluent_kafka` snippet.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# An Avro schema, as the `schema` argument wants it. `logicalType` is the part
# JSON cannot express: the consumer decodes `occurred_at` as a timestamp rather
# than as the integer it is on the wire.
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
        topic="${D0__DB}.avro_events",
        data_format="avro",
        schema=EVENT_SCHEMA,
        dlq_topic="${D0__DB}.dead",
        src_cfg={
            "kafka.consume_timeout_seconds": 2,
            "kafka.connection_timeout_seconds": 10,
            "tabsdata.kafka.trigger.max_bytes": 1048576,
        },
    ),
    flush_interval_mins=1,
    output_tables=["avro_events"],
)
def read_avro(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
