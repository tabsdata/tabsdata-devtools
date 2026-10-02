#
# Copyright 2026 Tabsdata Inc.
#

"""perf_kafka — the Kafka stream source read for throughput (performance/kafka_json).

One ``@stream_publisher`` over ``<prefix>.employees``, which the suite fills
with a million of the employees model's rows as JSON -- ten passes of the
redpanda domain's own ``modify-data`` -- BEFORE registering it, so it reads a
backlog as fast as it can. ``scripts/cdc_throughput.py`` measures it as it
measures a CDC stream: the shared stream ledger logs every file it writes, for
any stream source.

The JSON Schema is typed and requires every field: the connector validates
each message against it, which is part of what a JSON source costs and so part
of what is measured.

Buffer and trigger as the CDC performance publishers have them: large row
limits make a few large files and versions rather than many small ones, and
the buffer's 2-second time limit -- what the last partial buffer waits before
it is written, which ends the measured time -- keeps that wait from swamping a
backlog read in seconds.
"""

from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

_FIELDS = {
    "emp_no": "integer",
    "birth_date": "string",
    "first_name": "string",
    "last_name": "string",
    "gender": "string",
    "hire_date": "string",
}
_SCHEMA = json.dumps({
    "type": "object",
    "properties": {k: {"type": v} for k, v in _FIELDS.items()},
    "required": list(_FIELDS),
})

_CFG = {
    "kafka.consume_timeout_seconds": 2,
    "kafka.connection_timeout_seconds": 10,
    "tabsdata.kafka.buffer.max_rows": 200_000,
    "tabsdata.kafka.buffer.max_secs": 2,
    "tabsdata.kafka.trigger.max_rows": 500_000,
    "tabsdata.kafka.trigger.max_secs": 60,
}


@stream_publisher(
    source=KafkaStreamSrc(
        topic="${D0__DB}.employees",
        data_format="json",
        schema=_SCHEMA,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["perf_employees"],
)
def kafka_json(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows)
