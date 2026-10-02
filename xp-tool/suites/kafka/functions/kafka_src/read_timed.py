#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: the SAME topic on a TIME trigger.

`tabsdata.kafka.trigger.max_secs` stages a batch every N seconds whatever the
count. That is the axis to pick when LATENCY matters more than batch size — a
quiet topic still produces a table version every 60 seconds here, the shortest
interval allowed, where a count trigger would leave those few messages waiting
until `flush_interval_mins`.

The three axes combine: once 60 seconds have passed since the last batch,
whichever threshold has fired closes the next one. Setting a count AND a longer
time bound is the usual production shape — "at most 5000 messages or 300 seconds,
whichever comes first".

WHY THIS FUNCTION HAS ITS OWN COLLECTION
    Every registered stream publisher joins its CONNECTION's consumer group, and
    a redpanda domain's topics have a SINGLE PARTITION — so two publishers in the
    same group reading the same topic leave one of them permanently idle. This
    one reads `<prefix>.employees`, which `read_json` also reads, so it needs a
    different group: hence its own collection, wired to
    `connections/kafka_topic_in_time.yaml`, whose only difference is `group_id`.

    Publishers on DIFFERENT topics can share a group, which is why the other four
    functions in this suite sit together -- with cooperative rebalancing (the
    template sets it): each one registering rebalances the group, and the default
    protocol takes every member's partitions away and back, so a member re-reads
    what it had not committed. That staged the seeded employees twice.
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
            "tabsdata.kafka.poll.max_secs": 2,
            "kafka.connect_timeout_secs": 10,
            "tabsdata.kafka.trigger.max_secs": 60,
        },
    ),
    flush_interval_mins=1,
    output_tables=["employees_timed"],
)
def read_timed(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
