#
# Copyright 2026 Tabsdata Inc.
#

"""EXAMPLE — Kafka source: a DEAD-LETTER TOPIC.

`dlq_topic` is where a message goes when it cannot be turned into a row — a
deserialization failure, or a payload that violates `schema`. It is PRODUCED
there and the stream carries on, so ONE BAD MESSAGE CANNOT STOP INGESTION.
Without a DLQ that same message is an error, and the batch fails.

PUT THE DLQ UNDER THE DOMAIN'S OWN PREFIX, as here. Destroying the domain deletes
`<prefix>` and every `<prefix>.*` topic with it; a sibling `<prefix>_dead` would
outlive the run it belongs to.

A DLQ is not a place to forget about. Nothing drains it, and a topic that fills
up with rejected messages is the shape of an upstream contract change nobody
noticed — subscribe to it, or at least alert on its depth.

SEEING IT WORK
    The 9 seeded department messages all validate; the suite then sends a batch
    with `modify-data --entity departments --schema-changes drop`, every other
    message without `dept_name`. It is required, so those land in `<prefix>.dead`
    rather than in the table, and the suite reads them back to count them.

A ROLLOVER OF 5 OVER 9 MESSAGES also shows the other half of the batching rule:
one batch closes on the count, and the remaining 4 messages wait for
`flush_interval_mins` to roll them over. Both paths in one function.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# Both fields are REQUIRED, which is what makes a violating message possible —
# and therefore what makes the dead-letter path demonstrable.
DEPARTMENT_SCHEMA = json.dumps({
    "title": "Department",
    "type": "object",
    "properties": {
        "dept_no": {"type": "string"},
        "dept_name": {"type": "string"},
    },
    "required": ["dept_no", "dept_name"],
})


@stream_publisher(
    source=KafkaStreamSrc(
        topic="${D0__DB}.departments",
        data_format="json",
        schema=DEPARTMENT_SCHEMA,
        dlq_topic="${D0__DB}.dead",
        src_cfg={
            "kafka.consume_timeout_seconds": 2,
            "kafka.connection_timeout_seconds": 10,
            "tabsdata.kafka.trigger.max_rows": 5,
        },
    ),
    flush_interval_mins=1,
    output_tables=["departments"],
)
def read_dlq(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
