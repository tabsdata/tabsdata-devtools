#
# Copyright 2026 Tabsdata Inc.
#

"""caps_kafka — exercise the Kafka stream source (``@stream_publisher``) against a
redpanda domain, consuming THE DOMAIN'S OWN TOPICS. Kafka is SOURCE-ONLY here: the
connector registers a stream source and no destination, so there is nothing to write
back to a topic.

Like the CDC suites these are STREAM publishers: long-lived consumers that stay running
and close a batch each time a ROLLOVER threshold fires (message count, time or size) or
``flush_interval_mins`` rolls the window over. Cardinality is always 1 (one topic -> one
slot), the slot is an ARRAY of the frames that flush carried, and there is NO ``ctx``
parameter.

NO TRIGGER IS INVOLVED: registering a stream publisher STARTS it. The worker comes up
seconds after ``create-project`` and runs until the function is disabled or deleted
(``tdk worker list`` shows it; it carries no execution plan or transaction).

WHERE THE MESSAGES COME FROM. A redpanda domain IS a Kafka topic namespace: its data
plane produces a model's rows as JSON, ONE MESSAGE PER ROW, to ``<prefix>.<entity>`` —
one topic per model entity, created by create-model. The suite's domain carries the
``employees`` model at size ``xs``, so ``create-domains`` seeds:

    <prefix>.employees      100 messages   {emp_no, birth_date, first_name,
                                            last_name, gender, hire_date}
    <prefix>.departments      9 messages   {dept_no, dept_name}
    <prefix>.dept_emp / .dept_manager / .titles / .salaries   (derived, not consumed)

``<prefix>`` is the domain's in-system name, which tdx-xp derives PER RUN
(``xp_<user>_<ts>_redpanda``). ``KafkaStreamSrc.topic`` is fixed when the function is
written, so ``_PREFIX`` below is not a literal but a ``${…}`` reference to the backing
domain's ``DB`` (``D0`` is the collection's backing domain in kafka.json, ``DB`` its
in-system name), which tdx-xp interpolates when it registers this file — leaving the
rendered copy it registered in ``<scratch>/fn/<collection>/``. Nothing is pinned, so two
instances of the suite can run at once, each consuming its own topics.

To append more messages (a Kafka log only appends, so redpanda's ``modify-data`` is
insert-only and REJECTS anything else):

    tdx-domain modify-data --domain <instance>_redpanda --entity employees \\
        --ops Insert --sets 20

Dates arrive as ISO strings: the producer serializes each row with
``json.dumps(..., default=str)``. The ``schema`` argument is required for every payload
format and here is a JSON Schema — note the connector uses it to VALIDATE each message
(a violation raises and is routed to the DLQ), while the parquet column types are
inferred from the decoded JSON.

Variants — one COLLECTION each, because every registered stream publisher joins its
connection's consumer group and these topics have a single partition, so two consumers in
one group would leave one idle (templates: kafka_topic_in.yaml / _dlq / _time):
- ``kafka_in``      : base — ``<prefix>.employees`` with
                      ``tabsdata.kafka.trigger.max_rows=25`` -> the 100 seeded
                      messages arrive at once and are staged as one table version
                      once the 60-second manifest floor passes.
- ``kafka_in_dlq``  : ``<prefix>.departments`` (9 messages) with a ``dlq_topic``. The
                      seeded messages all validate; the suite then sends departments
                      with ``--schema-changes drop``, and every other message,
                      without the required ``dept_name``, goes to ``<prefix>.dead``,
                      which kafka_dead reads back. A row trigger of 5 is reached at once, but nothing is staged
                      before the 60-second manifest floor, so all 9 messages land
                      in one table version.
- ``kafka_in_time`` : ``<prefix>.employees`` again (own consumer group, so it sees every
                      message too) with ``tabsdata.kafka.trigger.max_secs`` marked
                      down to 15 seconds (``unsafe_seconds(15)``, below the 60-second
                      floor, for tests only) — staged on TIME rather than count.

The consumer forces ``auto.offset.reset=earliest`` and commits its offsets only once a
batch is staged, so it does not matter whether the worker starts before or after the
topics are seeded, and a re-run resumes from the last staged position. A topic that does
not exist yet is not fatal either: the poll loop logs the unknown-topic error and keeps
going until it appears.

``tabsdata.kafka.trigger.max_bytes`` is the third trigger axis and is not exercised: it
would take megabytes of messages to fire. ``avro`` and ``Protobuf(...)`` formats are also left out —
the redpanda data plane produces JSON, and both alternatives would need an encoder.
"""
from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher

# noinspection PyProtectedMember
from tabsdatak.conn.common._stream._floor import unsafe_seconds
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

# The backing domain's in-system name, interpolated by tdx-xp at registration (the
# domain's data plane produces to `<prefix>.<entity>`). Left as a `${…}` reference so
# the topics are per-run rather than pinned — see the module docstring.
_PREFIX = "${D0__DB}"
_EMP_TOPIC = f"{_PREFIX}.employees"
_DEPT_TOPIC = f"{_PREFIX}.departments"
# Dead-letter target: auto-created on the first bad message. Under the domain's prefix
# so it is per-run too AND is dropped with the domain (destroy deletes `<prefix>` and
# every `<prefix>.*` topic); a sibling `<prefix>_dead` would outlive it.
_DEAD_TOPIC = f"{_PREFIX}.dead"

# JSON Schemas matching what the employees model produces. Dates are ISO strings
# (`json.dumps(..., default=str)`), so they are typed as strings here.
_EMP_SCHEMA = json.dumps({
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
    "required": [
        "emp_no",
        "birth_date",
        "first_name",
        "last_name",
        "gender",
        "hire_date",
    ],
})
_DEPT_SCHEMA = json.dumps({
    "title": "Department",
    "type": "object",
    "properties": {
        "dept_no": {"type": "string"},
        "dept_name": {"type": "string"},
    },
    "required": ["dept_no", "dept_name"],
})

# Short consume timeout so the poll loop reacts quickly to a fresh message instead of
# blocking; the trigger knobs are per-variant below.
_CFG = {
    "tabsdata.kafka.poll.max_secs": 2,
    "kafka.connect_timeout_secs": 10,
}


# `concat` drops None entries and returns None for an empty/None list, so it doubles as
# the "this flush carried nothing" guard. Vertical (strict) on purpose: a payload whose
# shape drifts should surface here rather than be absorbed silently.
@stream_publisher(
    source=KafkaStreamSrc(
        topic=_EMP_TOPIC,
        data_format="json",
        schema=_EMP_SCHEMA,
        src_cfg=_CFG | {"tabsdata.kafka.trigger.max_rows": 25},
    ),
    flush_interval_mins=1,
    output_tables=["kafka_employees"],
)
def kafka_in(rows: TableFramesSpec) -> TableFrameSpec:
    # 100 seeded messages / 25 per batch -> 4 batches, then whatever modify-data appends.
    return concat(rows)


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_DEPT_TOPIC,
        data_format="json",
        schema=_DEPT_SCHEMA,
        dlq_topic=_DEAD_TOPIC,
        src_cfg=_CFG | {"tabsdata.kafka.trigger.max_rows": 5},
    ),
    flush_interval_mins=1,
    output_tables=["kafka_departments"],
)
def kafka_in_dlq(rows: TableFramesSpec) -> TableFrameSpec:
    # 9 seeded messages: the row trigger of 5 is reached at once, and all 9 are staged
    # together once the 60-second floor passes.
    # A message that fails schema validation goes to <prefix>.dead instead of here.
    return concat(rows)


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_EMP_TOPIC,
        data_format="json",
        schema=_EMP_SCHEMA,
        src_cfg=_CFG | {"tabsdata.kafka.trigger.max_secs": unsafe_seconds(15)},
    ),
    flush_interval_mins=1,
    output_tables=["kafka_timed"],
)
def kafka_in_time(rows: TableFramesSpec) -> TableFrameSpec:
    # Same topic as the base variant, own consumer group -> it sees every message too,
    # but batches on a 15s clock (marked below the floor) instead of a message count.
    return concat(rows)
