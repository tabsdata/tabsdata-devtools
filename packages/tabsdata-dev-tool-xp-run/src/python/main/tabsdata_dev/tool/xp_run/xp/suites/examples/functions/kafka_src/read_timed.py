#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: the SAME topic on a TIME rollover.

`kafka.time_rollover_seconds` closes a batch every N seconds whatever the count.
That is the axis to pick when LATENCY matters more than batch size — a quiet
topic still produces a table version every 15 seconds here, where a count
rollover would leave those few messages buffered until `flush_interval_mins`.

The three axes combine: whichever threshold fires first closes the batch. Setting
a count AND a time bound is the usual production shape — "at most 5000 messages
or 60 seconds, whichever comes first".

WHY THIS FUNCTION HAS ITS OWN COLLECTION
    Every registered stream publisher joins its CONNECTION's consumer group, and
    a redpanda domain's topics have a SINGLE PARTITION — so two publishers in the
    same group reading the same topic leave one of them permanently idle. This
    one reads `<prefix>.employees`, which `read_json` also reads, so it needs a
    different group: hence its own collection, wired to
    `connections/kafka_topic_in_time.yaml`, whose only difference is `group_id`.

    Publishers on DIFFERENT topics share a group happily, which is why the other
    four functions in this suite sit together.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# Same schema as read_json.py — same topic, same messages, different cadence.
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
            "kafka.consume_timeout_seconds": 2,
            "kafka.connection_timeout_seconds": 10,
            "kafka.time_rollover_seconds": 15,
        },
    ),
    flush_interval_mins=1,
    output_tables=["employees_timed"],
)
def read_timed(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
