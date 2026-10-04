#
# Copyright 2026 Tabsdata Inc.
#

"""perf_kafka — the Kafka stream source read for throughput (performance/kafka_json).

One ``@stream_publisher`` over ``<prefix>.employees``, which the suite fills
with ten million of the employees model's rows as JSON -- forty passes of the
redpanda domain's own ``modify-data`` -- BEFORE registering it, so it reads a
backlog as fast as it can. ``scripts/cdc_throughput.py`` measures it as it
measures a CDC stream: the shared stream ledger logs every file it writes, for
any stream source.

The JSON Schema is typed and requires every field: the connector validates
each message against it, which is part of what a JSON source costs and so part
of what is measured.

Tuned to read the backlog as fast as the source can, and to measure only that:

- ``tabsdata.kafka.buffer.max_rows`` 1,000,000 divides the ten million, so
  files are written on their row count -- about ten, each soon after the
  last -- and only a final partial one, if a fetch boundary leaves one, waits
  out ``buffer.max_secs`` (2) at the end. ``cdc_throughput.py``'s read figure
  and its steady rate leave that wait and the stream's start out.
- ``tabsdata.kafka.consume.max_messages`` 100,000, what librdkafka prefetches
  into its local queue (``queued.min.messages``), so each fetch hands over
  the most it can and the typed schema lets the source decode the whole
  fetch as one Arrow table; a larger fetch would wait out the poll.
- ``tabsdata.kafka.poll.max_secs`` 1, the shortest the source accepts (a
  whole number of seconds, at least 1).
- The connection (``kafka_topic_in_perf.yaml``) sets librdkafka's
  ``fetch.queue.backoff.ms`` to 0, so the consumer never stalls waiting for
  its next fetch.

The trigger's limits come after the files, outside what is measured.
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
    "tabsdata.kafka.poll.max_secs": 1,
    "kafka.connect_timeout_secs": 10,
    "tabsdata.kafka.consume.max_messages": 100_000,
    "tabsdata.kafka.buffer.max_rows": 1_000_000,
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
