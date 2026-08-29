#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: PROTOBUF payloads.

Protobuf is the one format whose `data_format` is not a string: it is a
`Protobuf(message_name=...)` MARKER, because a `.proto` file can define many
messages and the consumer has to be told which one is on this topic. The
`schema` argument then carries the `.proto` SOURCE itself.

    data_format=Protobuf(message_name="com.example.UserEvent")
    schema="<the .proto text>"

The `message_name` must be the FULLY-QUALIFIED name — package included — or the
descriptor lookup fails at decode time, which surfaces as everything going to the
DLQ rather than as a configuration error.

Like the Avro example, nothing produces to this topic here: an unknown topic is
not fatal, so the configuration is documented without an encoder in the harness.
"""
from __future__ import annotations

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc, Protobuf
from tabsdatak.tableframe.functions import concat

# The .proto source. `schema` takes the text, not a path and not a compiled
# descriptor.
USER_EVENT_PROTO = """
syntax = "proto3";
package com.example;

message UserEvent {
  int64 event_id = 1;
  string kind = 2;
  string payload = 3;
  int64 occurred_at = 4;
}
"""


@stream_publisher(
    source=KafkaStreamSrc(
        topic="${D0__DB}.proto_events",
        data_format=Protobuf(message_name="com.example.UserEvent"),
        schema=USER_EVENT_PROTO,
        dlq_topic="${D0__DB}.dead",
        src_cfg={
            "kafka.consume_timeout_seconds": 2,
            "kafka.connection_timeout_seconds": 10,
            "kafka.messages_rollover": 50,
        },
    ),
    flush_interval_mins=1,
    output_tables=["proto_events"],
)
def read_protobuf(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
