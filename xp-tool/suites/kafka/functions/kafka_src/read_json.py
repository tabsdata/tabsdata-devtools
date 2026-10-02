#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: JSON payloads, with a COUNT trigger.

SHAPE OF A KAFKA STREAM
    `@stream_publisher`, like CDC: registering it STARTS it, so there is no
    trigger and no `ctx`. One topic means ONE slot, and the slot is an ARRAY of
    the frames the flush carried — fold it with `concat`. The emitted table name
    is the topic, and every batch carries a `@td.kafka.topic` column.

FORMAT — `data_format` AND `schema`, BOTH ALWAYS REQUIRED
    `"json"` with a JSON Schema (here), `"avro"` with an Avro schema, or
    `Protobuf(message_name=...)` with the `.proto` source. The schema is not
    documentation: the connector VALIDATES every message against it, and a
    violation is routed to the DLQ (or fails the batch when there is none).

    The COLUMN TYPES come from the decoded payload, not from the schema: a
    `{"format": "date"}` string stays a string. Cast downstream if you need a
    real date.

    The schema is the one thing in these examples kept as a module CONSTANT
    rather than inlined in the decorator — it is a document, not a setting, and
    reading the configuration past 30 lines of JSON helps nobody.

TWO LEVELS — buffer files, trigger batches, both in `src_cfg`
    The `tabsdata.kafka.buffer.*` keys (`max_rows`, `max_bytes`, `max_secs`)
    decide when the buffered messages are written to a parquet file. The
    `tabsdata.kafka.trigger.*` keys decide when the written files are staged as
    one batch, whichever fires first:

    `tabsdata.kafka.trigger.max_rows`   after N messages             (this file)
    `tabsdata.kafka.trigger.max_secs`   after N seconds, at least 60 (read_timed.py)
    `tabsdata.kafka.trigger.max_bytes`  after N bytes                (read_avro.py)

    A batch never comes sooner than 60 seconds after the previous one: a row or
    byte trigger reached earlier is staged at that mark. `flush_interval_mins`
    caps the time trigger, so a batch is never stuck waiting for a threshold
    that will not be reached.

WHERE THE MESSAGES COME FROM
    A redpanda domain IS a topic namespace: its data plane produces a model's
    rows as JSON, ONE MESSAGE PER ROW, to `<prefix>.<entity>`. This suite's
    domain carries the `employees` model at size `xs`, so `create-domains` seeds
    `<prefix>.employees` (100 messages) and `<prefix>.departments` (9).

    `<prefix>` is the domain's PER-RUN in-system name, and `topic` is fixed when
    the function is written — so it is written as a `${D0__DB}` reference, which
    tdx-xp interpolates at registration time (leaving the rendered copy in
    `<scratch>/fn/<collection>/`). That is what lets two instances of this suite
    run at once, each on its own topics.

    Append more messages at any time — a Kafka log only appends, so redpanda's
    `modify-data` is insert-only and rejects anything else:

        tdx-domain modify-data --domain <instance>_redpanda \\
            --entity employees --ops Insert --sets 20

    The consumer forces `auto.offset.reset=earliest` and never commits offsets,
    so it does not matter whether the worker starts before or after the topic is
    seeded, and a re-run re-reads from the beginning.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# The JSON Schema every message on this topic must satisfy. Dates arrive as ISO
# strings (the producer serialises each row with `json.dumps(..., default=str)`),
# so they are typed as strings here.
EMPLOYEE_SCHEMA = json.dumps({
    "title": "Employee",
    "type": "object",
    "properties": {
        "emp_no": {"type": "integer"},
        "birth_date": {"type": "string", "format": "date"},
        "first_name": {"type": "string"},
        "last_name": {"type": "string"},
        "gender": {"type": "string"},
        "hire_date": {"type": "string", "format": "date"},
    },
    "required": ["emp_no", "first_name", "last_name"],
})


@stream_publisher(
    source=KafkaStreamSrc(
        topic="${D0__DB}.employees",
        data_format="json",
        schema=EMPLOYEE_SCHEMA,
        src_cfg={
            "tabsdata.kafka.poll.max_secs": 2,
            "kafka.connect_timeout_secs": 10,
            # 100 seeded messages / 25 per batch -> 4 batches.
            "tabsdata.kafka.trigger.max_rows": 25,
        },
    ),
    flush_interval_mins=1,
    output_tables=["employees"],
)
def read_json(rows: TableFramesSpec) -> TableFrameSpec:
    # `concat` drops Nones and returns None for an empty list, so it doubles as
    # the "this flush carried nothing" guard.
    return concat(rows)
