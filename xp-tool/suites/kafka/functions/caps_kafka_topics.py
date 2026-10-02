#
# Copyright 2026 Tabsdata Inc.
#

"""caps_kafka_topics — Kafka stream publishers over SEVERAL topics, topics of
several partitions, and messages whose shape varies, against a redpanda domain.

ONE PUBLISHER, SEVERAL TOPICS. ``KafkaStreamSrc`` takes one ``topic``, and the
consumer subscribes to exactly that string -- which librdkafka reads as a
REGULAR EXPRESSION when it starts with ``^``. So a publisher of three topics is
one whose topic is ``^<prefix>\\.(a|b|c)$``. Everything it reads still lands in
its ONE slot: the frames of a flush come mixed, and its ``@td.kafka.topic``
column holds the pattern, not the topic a message came from. A frame never
mixes topics, though -- the encoder starts a new frame whenever a message's
fields are not a subset of the frame's, and these topics' fields differ -- so
``_route`` sends each frame to its topic's table by the columns it has, and
anything it cannot place to ``kafka_unrouted``, which a check expects empty.

The topics exist before the publisher subscribes: a redpanda domain's
``create-model`` creates every entity's topic (``--up-to-partitions`` giving
them different partition counts), so a regex subscription sees them all at once,
and a topic nothing writes to is subscribed to and stays silent. The one schema
validates every topic's messages: an ``anyOf`` of each entity's.

WHERE THE MESSAGES COME FROM. The domain's data plane produces a model's rows as
JSON, one message per row keyed by its first field, to ``<prefix>.<entity>``;
``tdd domain create-data``/``modify-data --entity A,B`` write only those
topics, and ``--schema-changes`` varies the rows (an extra ``xp_extra`` field, a
last field left out, a first field of another JSON type). ``<prefix>`` is the
domain's per-run in-system name, written ``${D0__DB}`` and interpolated by xp
at registration, so concurrent runs never share a topic or a group.

Publishers -- each suite's collections say which run together:
- ``kafka_three_of_four``  departments (1), employees (2), dept_emp (3 partitions
                           with --up-to-partitions 4), while the suite also
                           writes salaries, which it does not subscribe to.
- ``kafka_two_of_three``   departments, employees and titles; the suite writes
                           only the first two, so kafka_titles stays empty.
- ``kafka_one_topic``      dept_manager alone (4 partitions): one consumer owns
                           every partition.
- ``kafka_shared_a`` / ``kafka_shared_b``  dept_emp (3 partitions), both in ONE
                           consumer group, which splits the partitions between
                           them: what one reads the other does not, unless a
                           rebalance hands a partition over before its offsets
                           were committed -- then both stage it.
- ``kafka_varied``         employees and departments with schema changes:
                           typed schemas requiring only each entity's first
                           field, so an ``add`` or ``drop`` row validates (and
                           ``diagonal_relaxed`` folds the differing frames into
                           one table) and a ``retype`` row is refused and goes
                           to ``<prefix>.dead``.
- ``kafka_dead``           ``<prefix>.dead``: the dead-letter envelopes
                           ({original_value, error, topic, partition, offset,
                           timestamp}), so a check can account for every
                           message refused.
"""

from __future__ import annotations

import json

from tabsdatak.api import TableFrameSpec, TableFramesSpec, stream_publisher

# noinspection PyProtectedMember
from tabsdatak.conn.common._stream._floor import unsafe_seconds
from tabsdatak.conn.kafka import KafkaStreamSrc
from tabsdatak.tableframe.functions import concat

_PREFIX = "${D0__DB}"
_DEAD_TOPIC = f"{_PREFIX}.dead"


def _topics(*entities: str) -> str:
    """The regex subscription to `entities`' topics. The prefix is letters,
    digits and `_` only; the dot is escaped."""
    return f"^{_PREFIX}\\.({'|'.join(entities)})$"


def _object(required: str, **properties: str) -> dict:
    return {
        "type": "object",
        "properties": {k: {"type": v} for k, v in properties.items()},
        "required": [required],
    }


# Each entity's messages, typed; only the first field required, so a row
# `--schema-changes drop` left its last field off still validates. Dates are
# ISO strings (the producer serializes with `default=str`); nullable fields
# take null too.
_ENTITY = {
    "departments": _object("dept_no", dept_no="string", dept_name="string"),
    "employees": _object(
        "emp_no",
        emp_no="integer",
        birth_date="string",
        first_name="string",
        last_name="string",
        gender="string",
        hire_date="string",
    ),
    "dept_emp": _object(
        "emp_no", emp_no="integer", dept_no="string", from_date="string", to_date="string"
    ),
    "dept_manager": _object(
        "emp_no", emp_no="integer", dept_no="string", from_date="string", to_date="string"
    ),
    "titles": _object("emp_no", emp_no="integer", title="string", from_date="string"),
}


def _schema(*entities: str) -> str:
    return json.dumps({"anyOf": [_ENTITY[e] for e in entities]})


# What tells a frame's topic: a column only that entity's messages have. Order
# matters: dept_emp is told from departments by emp_no.
_MARKS = {
    "departments": lambda cols: "dept_no" in cols and "emp_no" not in cols,
    "employees": lambda cols: "first_name" in cols,
    "dept_emp": lambda cols: {"emp_no", "dept_no"} <= cols,
    "titles": lambda cols: "title" in cols,
}


def _route(frames, *entities: str) -> tuple:
    """Each frame to the first of `entities` whose mark it has, the rest to a
    last, unrouted slot; each slot folded with diagonal_relaxed -- frames of one
    topic may differ in their columns (a dropped or extra field, a column all
    null in one flush). None for a slot the flush carried nothing for."""
    slots: list[list] = [[] for _ in range(len(entities) + 1)]
    for frame in frames or []:
        if frame is None:
            continue
        cols = set(frame.columns)
        for i, entity in enumerate(entities):
            if _MARKS[entity](cols):
                slots[i].append(frame)
                break
        else:
            slots[-1].append(frame)
    return tuple(concat(s, how="diagonal_relaxed") for s in slots)


# Batches staged promptly: a short trigger (marked below the 60s floor, for
# tests only) and a short poll, so a suite's check sees the messages soon after
# they were produced.
_CFG = {
    "tabsdata.kafka.poll.max_secs": 2,
    "kafka.connect_timeout_secs": 10,
    "tabsdata.kafka.trigger.max_secs": unsafe_seconds(15),
}

_Out3 = tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec, TableFrameSpec]
_Out2 = tuple[TableFrameSpec, TableFrameSpec, TableFrameSpec]


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_topics("departments", "employees", "dept_emp"),
        data_format="json",
        schema=_schema("departments", "employees", "dept_emp"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_departments", "kafka_employees", "kafka_dept_emp", "kafka_unrouted"],
)
def kafka_three_of_four(rows: TableFramesSpec) -> _Out3:
    return _route(rows, "departments", "employees", "dept_emp")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_topics("departments", "employees", "titles"),
        data_format="json",
        schema=_schema("departments", "employees", "titles"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_departments", "kafka_employees", "kafka_titles", "kafka_unrouted"],
)
def kafka_two_of_three(rows: TableFramesSpec) -> _Out3:
    # titles is subscribed to and never written: kafka_titles must stay empty.
    return _route(rows, "departments", "employees", "titles")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.dept_manager",
        data_format="json",
        schema=_schema("dept_manager"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_dept_manager"],
)
def kafka_one_topic(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.dept_emp",
        data_format="json",
        schema=_schema("dept_emp"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_shared_a"],
)
def kafka_shared_a(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.dept_emp",
        data_format="json",
        schema=_schema("dept_emp"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_shared_b"],
)
def kafka_shared_b(rows: TableFramesSpec) -> TableFrameSpec:
    # Same topic and group as kafka_shared_a: the two split its partitions.
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_topics("departments", "employees"),
        data_format="json",
        schema=_schema("departments", "employees"),
        dlq_topic=_DEAD_TOPIC,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_departments", "kafka_employees", "kafka_unrouted"],
)
def kafka_varied(rows: TableFramesSpec) -> _Out2:
    return _route(rows, "departments", "employees")


_DEAD_SCHEMA = json.dumps({
    "type": "object",
    "properties": {"original_value": {"type": ["string", "null"]}, "topic": {"type": "string"}},
    "required": ["original_value", "topic"],
})


@stream_publisher(
    source=KafkaStreamSrc(
        topic=_DEAD_TOPIC,
        data_format="json",
        schema=_DEAD_SCHEMA,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_dead"],
)
def kafka_dead(rows: TableFramesSpec) -> TableFrameSpec:
    # The envelope's `timestamp` is a [type, millis] pair: a list column, which
    # no CSV reader of the table can take, and nothing a check compares.
    frame = concat(rows, how="diagonal_relaxed")
    if frame is None:
        return None
    return frame.select("original_value", "error", "topic", "partition", "offset")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.registry_dead",
        data_format="json",
        schema=_DEAD_SCHEMA,
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_registry_dead"],
)
def kafka_registry_dead(rows: TableFramesSpec) -> TableFrameSpec:
    # The registry example's dead letters: plain messages a registry consumer
    # cannot decode. Same envelope, same columns kept, as kafka_dead.
    frame = concat(rows, how="diagonal_relaxed")
    if frame is None:
        return None
    return frame.select("original_value", "error", "topic", "partition", "offset")


# TRIGGERS. Three publishers over the same topic, each in a group of its own,
# whose only difference is what may stage a batch before a 10-minute clock: the
# time trigger and flush_interval_mins are both 10 minutes, so a batch staged
# within minutes was staged by the byte or row count. The control has neither,
# and must stage nothing for those 10 minutes.
_SLOW = {
    "tabsdata.kafka.poll.max_secs": 2,
    "kafka.connect_timeout_secs": 10,
    "tabsdata.kafka.trigger.max_secs": 600,
}


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.employees",
        data_format="json",
        schema=_schema("employees"),
        # ~130 bytes a message: a few dozen messages fill it.
        src_cfg=_SLOW | {"tabsdata.kafka.trigger.max_bytes": 4096},
    ),
    flush_interval_mins=10,
    output_tables=["kafka_by_bytes"],
)
def kafka_by_bytes(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.employees",
        data_format="json",
        schema=_schema("employees"),
        src_cfg=_SLOW | {"tabsdata.kafka.trigger.max_rows": 50},
    ),
    flush_interval_mins=10,
    output_tables=["kafka_by_rows"],
)
def kafka_by_rows(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.employees",
        data_format="json",
        schema=_schema("employees"),
        src_cfg=_SLOW,
    ),
    flush_interval_mins=10,
    output_tables=["kafka_by_time"],
)
def kafka_by_time(rows: TableFramesSpec) -> TableFrameSpec:
    return concat(rows, how="diagonal_relaxed")


@stream_publisher(
    source=KafkaStreamSrc(
        topic=f"{_PREFIX}.employees",
        data_format="json",
        schema=_schema("employees"),
        src_cfg=_CFG,
    ),
    flush_interval_mins=1,
    output_tables=["kafka_resumed"],
)
def kafka_resume(rows: TableFramesSpec) -> TableFrameSpec:
    # Disabled and enabled again by its suite: it must go on from the offsets
    # it committed, no message lost and none staged twice.
    return concat(rows, how="diagonal_relaxed")
