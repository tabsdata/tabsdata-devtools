#
# Copyright 2026 Tabsdata Inc.
#

"""How a redpanda domain's messages are encoded: JSON, Avro or Protobuf, plain
or in the Confluent schema-registry wire format.

A model names the entities whose messages are not JSON (``model.json``'s
``message_formats``, :func:`datagen.message_formats`); ``create-model`` records
them in the domain's meta (``MESSAGE_FORMATS``). ``domain create
--message-format json|avro|protobuf`` records the format of every other entity
(``MESSAGE_FORMAT``, default JSON), and ``--registry on`` records ``REGISTRY``.
A table whose names the format cannot hold (Avro and Protobuf names are
identifiers, bronze's ``@td.cdc.*`` columns are not) is left out of it -- its
topic gets no messages, and the run says so -- as a file domain leaves it out
of its Avro files. Every schema is made from the entity's
columns -- the ones a message carries, ``auto`` ones left out -- so nothing is
kept beside the model to drift from it:

* **Avro** is :func:`emit.avro_schema`, the record files are written with
  too; plain, a message is the record's binary encoding with no header (what a
  registry-less Avro source decodes with the schema it is given).
* **Protobuf** is one ``.proto`` per entity, ``package tdd``, one message named
  after the entity in CamelCase (``order_placed`` -> ``tdd.OrderPlaced``, the
  ``message_name`` a consumer asks for), a field per column numbered in column
  order, a nullable column ``optional`` so a null is absent rather than zero.
  Protobuf has no decimal, date or time: those travel as their text (a decimal
  at its scale, ISO 8601). The descriptor is built here rather than compiled
  from the ``.proto`` text, which needs ``protoc``; :func:`proto_text` renders
  the same declaration for a consumer, and a test pins that the two agree.
* **Registry**: each schema is registered under ``<topic>-value`` (the
  TopicNameStrategy every Confluent client defaults to) and a message is
  ``0x00``, the schema id (4 bytes, big-endian), then -- Protobuf only -- the
  message index (``0x00``: the first message of its file), then the payload.
  The registry is redpanda's own, reached over its REST API with the standard
  library: registering a schema already there returns its id, so every run
  registers and no id is stored.
"""

from __future__ import annotations

import io
import json
import re
import struct
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable
from datetime import date, datetime, time
from decimal import Decimal

from tabsdata_dev.common.systems import datagen, emit
from tabsdata_dev.common.systems.errors import TdxError

#: The domain meta key holding ``{entity: avro|protobuf}`` (JSON).
META_MESSAGE_FORMATS = "MESSAGE_FORMATS"
#: The domain meta key holding the format of every entity the model does not
#: name (``domain create --message-format``; JSON when absent).
META_MESSAGE_FORMAT = "MESSAGE_FORMAT"
OPT_MESSAGE_FORMAT = "--message-format"
#: The domain meta key saying whether messages go in the registry wire format.
META_REGISTRY = "REGISTRY"
REGISTRY_ON, REGISTRY_OFF = "on", "off"
OPT_REGISTRY = "--registry"

#: The namespace (Avro) and package (Protobuf) of every schema.
NAMESPACE = "tdd"

_REGISTRY_CONTENT = "application/vnd.schemaregistry.v1+json"
# An Avro name and a Protobuf field name alike.
_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_REGISTRY_TIMEOUT = 30


def formats_of(meta: dict[str, str]) -> dict[str, str]:
    """The non-JSON entities a domain recorded; ``{}`` before create-model, or
    for a model whose messages are all JSON."""
    raw = meta.get(META_MESSAGE_FORMATS, "")
    if not raw:
        return {}
    try:
        return {str(k): str(v) for k, v in json.loads(raw).items()}
    except (json.JSONDecodeError, AttributeError) as exc:
        raise TdxError(
            f"domain meta {META_MESSAGE_FORMATS} is not JSON: {raw!r}"
        ) from exc


def encode_formats(formats: dict[str, str]) -> str:
    return json.dumps(formats, separators=(",", ":"), sort_keys=True)


def default_format(meta: dict[str, str]) -> str:
    """The format of a domain's entities its model does not name."""
    return meta.get(META_MESSAGE_FORMAT) or datagen.MESSAGE_JSON


def effective_formats(
    formats: dict[str, str], default: str, entities: list[str]
) -> dict[str, str]:
    """``{entity: avro|protobuf}`` for `entities`: the model's own format, else
    the domain's `default`; a JSON entity is left out, as in ``formats``."""
    out = {}
    for name in entities:
        fmt = formats.get(name, default)
        if fmt != datagen.MESSAGE_JSON:
            out[name] = fmt
    return out


def domain_formats(meta: dict[str, str], entities: list[str]) -> dict[str, str]:
    """:func:`effective_formats` from a domain's meta."""
    return effective_formats(formats_of(meta), default_format(meta), entities)


def unencodable(fmt: str, entity: str, columns: list[emit.Column]) -> str | None:
    """Why `entity`'s messages cannot be `fmt`, or ``None`` when they can: an
    Avro or Protobuf field is named by an identifier, which bronze's
    ``@td.cdc.*`` columns are not."""
    if fmt == datagen.MESSAGE_JSON:
        return None
    bad = [c.name for c in message_columns(columns) if not _IDENT.match(c.name)]
    if not _IDENT.match(entity):
        bad.insert(0, entity)
    if not bad:
        return None
    more = f" and {len(bad) - 3} more" if len(bad) > 3 else ""
    return f"not {fmt} names: {', '.join(bad[:3])}{more}"


def leave_out(
    tables: list[emit.Table], formats: dict[str, str]
) -> tuple[list[emit.Table], list[str]]:
    """`tables` but those whose messages their format cannot be (`formats` as
    :func:`effective_formats` gives them), and a line for each one left out."""
    kept, notes = [], []
    for t in tables:
        fmt = formats.get(t.name, datagen.MESSAGE_JSON)
        why = unencodable(fmt, t.name, t.columns)
        if why:
            notes.append(f"{t.name}: no {fmt} messages ({why})")
        else:
            kept.append(t)
    return kept, notes


def registry_of(meta: dict[str, str]) -> str:
    """The registry URL a domain's messages are framed for, or ``""``."""
    if meta.get(META_REGISTRY, REGISTRY_OFF) != REGISTRY_ON:
        return ""
    url = meta.get("SCHEMA_REGISTRY_URL", "")
    if not url:
        raise TdxError(f"domain has {OPT_REGISTRY} on but no SCHEMA_REGISTRY_URL")
    return url


def message_name(entity: str) -> str:
    """``order_placed`` -> ``OrderPlaced``."""
    return "".join(part[:1].upper() + part[1:] for part in entity.split("_") if part)


def message_columns(columns: list[emit.Column]) -> list[emit.Column]:
    """The columns a message carries: every one but the ``auto`` ones, as
    ``shape.record`` sends a row."""
    return [c for c in columns if not c.auto]


# ---- Avro -----------------------------------------------------------------


def avro_schema(entity: str, columns: list[emit.Column]) -> dict:
    return emit.avro_schema(message_name(entity), message_columns(columns), NAMESPACE)


def _avro_encoder(entity: str, columns: list[emit.Column]) -> Callable[[dict], bytes]:
    import fastavro

    cols = message_columns(columns)
    parsed = fastavro.parse_schema(avro_schema(entity, columns))

    def encode(record: dict) -> bytes:
        buf = io.BytesIO()
        fastavro.schemaless_writer(buf, parsed, emit.avro_record(record, cols))
        return buf.getvalue()

    return encode


# ---- Protobuf -------------------------------------------------------------

# proto3 scalar types by SQL type; a type not listed travels as its text.
_PROTO_SCALARS = {
    "tinyint": "int32",
    "smallint": "int32",
    "int": "int32",
    "integer": "int32",
    "bigint": "int64",
    "boolean": "bool",
    "bool": "bool",
    "float": "double",
    "double": "double",
    "real": "double",
}


def _proto_scalar(sql_type: str) -> str:
    return _PROTO_SCALARS.get(emit._norm(sql_type), "string")


def proto_text(entity: str, columns: list[emit.Column]) -> str:
    """The ``.proto`` declaration of the entity's message, for a consumer."""
    lines = ['syntax = "proto3";', "", f"package {NAMESPACE};", ""]
    lines.append(f"message {message_name(entity)} {{")
    for number, c in enumerate(message_columns(columns), start=1):
        label = "optional " if c.nullable else ""
        lines.append(f"  {label}{_proto_scalar(c.sql_type)} {c.name} = {number};")
    lines.append("}")
    return "\n".join(lines) + "\n"


def proto_descriptor(entity: str, columns: list[emit.Column]):
    """The ``FileDescriptorProto`` :func:`proto_text` declares. An ``optional``
    field is what protoc makes of one: a synthetic one-field oneof, named
    ``_<field>``."""
    from google.protobuf import descriptor_pb2

    fdp = descriptor_pb2.FieldDescriptorProto
    types = {
        "int32": fdp.TYPE_INT32,
        "int64": fdp.TYPE_INT64,
        "bool": fdp.TYPE_BOOL,
        "double": fdp.TYPE_DOUBLE,
        "string": fdp.TYPE_STRING,
    }
    file = descriptor_pb2.FileDescriptorProto(
        name=f"{entity}.proto", package=NAMESPACE, syntax="proto3"
    )
    msg = file.message_type.add(name=message_name(entity))
    for number, c in enumerate(message_columns(columns), start=1):
        field = msg.field.add(
            name=c.name,
            number=number,
            label=fdp.LABEL_OPTIONAL,
            type=types[_proto_scalar(c.sql_type)],
            json_name=_json_name(c.name),
        )
        if c.nullable:
            field.proto3_optional = True
            field.oneof_index = len(msg.oneof_decl)
            msg.oneof_decl.add(name=f"_{c.name}")
    return file


def _json_name(name: str) -> str:
    """protoc's lowerCamelCase JSON name, so a descriptor built here compares
    equal to one it compiles."""
    head, *rest = name.split("_")
    return head + "".join(p[:1].upper() + p[1:] for p in rest)


def proto_class(entity: str, columns: list[emit.Column]):
    """The message class of the entity, from its descriptor, in a pool of its
    own so two domains' same-named messages never meet."""
    from google.protobuf import descriptor_pool, message_factory

    pool = descriptor_pool.DescriptorPool()
    pool.Add(proto_descriptor(entity, columns))
    found = pool.FindMessageTypeByName(f"{NAMESPACE}.{message_name(entity)}")
    return message_factory.GetMessageClass(found)


def _proto_value(v, sql_type: str):
    t = emit._norm(sql_type)
    scalar = _proto_scalar(sql_type)
    if scalar in ("int32", "int64"):
        return int(v)
    if scalar == "bool":
        return bool(v)
    if scalar == "double":
        return float(v)
    dec = emit._is_decimal(t)
    if dec:
        return str(Decimal(str(v)).quantize(Decimal(1).scaleb(-dec[1])))
    if isinstance(v, (date, datetime, time)):
        return v.isoformat()
    return str(v)


def _protobuf_encoder(
    entity: str, columns: list[emit.Column]
) -> Callable[[dict], bytes]:
    cls = proto_class(entity, columns)
    cols = message_columns(columns)

    def encode(record: dict) -> bytes:
        msg = cls()
        for c in cols:
            value = record.get(c.name)
            if value is not None:
                setattr(msg, c.name, _proto_value(value, c.sql_type))
        return msg.SerializeToString()

    return encode


# ---- the registry ---------------------------------------------------------


def subject(topic: str) -> str:
    return f"{topic}-value"


def _registry_call(url: str, method: str, body: dict | None = None):
    data = None if body is None else json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method, headers={"Content-Type": _REGISTRY_CONTENT}
    )
    with urllib.request.urlopen(req, timeout=_REGISTRY_TIMEOUT) as resp:
        return json.loads(resp.read().decode("utf-8") or "null")


def register(registry: str, topic: str, fmt: str, schema: str) -> int:
    """Register `schema` under the topic's subject; its id (the one it already
    has when it is registered)."""
    url = (
        f"{registry.rstrip('/')}/subjects/{urllib.parse.quote(subject(topic))}/versions"
    )
    body = {"schema": schema, "schemaType": fmt.upper()}
    try:
        return int(_registry_call(url, "POST", body)["id"])
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")
        raise TdxError(
            f"schema registry refused {subject(topic)} ({exc.code}): {detail}"
        ) from exc
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        raise TdxError(f"schema registry {registry}: {exc}") from exc


def delete_subjects(registry: str, prefix: str) -> list[str]:
    """Delete, soft then permanently, every ``<prefix>.<entity>-value``
    subject: a topic gone with its schema left behind would refuse an
    incompatible one under the same name later. What failed, by subject."""
    base = registry.rstrip("/")
    try:
        names = _registry_call(f"{base}/subjects", "GET") or []
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return [f"listing subjects ({exc})"]
    failed = []
    for name in names:
        if not (name.startswith(f"{prefix}.") and name.endswith("-value")):
            continue
        quoted = urllib.parse.quote(name)
        for suffix in ("", "?permanent=true"):
            try:
                _registry_call(f"{base}/subjects/{quoted}{suffix}", "DELETE")
            except urllib.error.HTTPError as exc:
                if exc.code != 404:
                    failed.append(f"{name} ({exc.code})")
                    break
            except (urllib.error.URLError, OSError) as exc:
                failed.append(f"{name} ({exc})")
                break
    return failed


def _framed(
    encode: Callable[[dict], bytes], schema_id: int, fmt: str
) -> Callable[[dict], bytes]:
    head = b"\x00" + struct.pack(">I", schema_id)
    if fmt == datagen.MESSAGE_PROTOBUF:
        head += b"\x00"  # message indexes [0], as the Confluent serializer writes it

    def encode_framed(record: dict) -> bytes:
        return head + encode(record)

    return encode_framed


# ---- the encoder a topic's messages go through ---------------------------


def schema_text(fmt: str, entity: str, columns: list[emit.Column]) -> str:
    """The schema a consumer is given for the entity's messages: the Avro
    schema as JSON, the ``.proto`` text."""
    if fmt == datagen.MESSAGE_AVRO:
        return json.dumps(avro_schema(entity, columns), indent=2) + "\n"
    if fmt == datagen.MESSAGE_PROTOBUF:
        return proto_text(entity, columns)
    raise TdxError(f"no schema for {fmt} messages")


def _json_encode(record: dict) -> bytes:
    return json.dumps(record, default=str, separators=(",", ":")).encode()


def encoder(
    fmt: str, topic: str, entity: str, columns: list[emit.Column], registry: str = ""
) -> Callable[[dict], bytes]:
    """The function a topic's records are encoded with. JSON is never framed:
    the registry carries the Avro and Protobuf schemas, and a JSON topic is
    read as it always was."""
    if fmt == datagen.MESSAGE_JSON:
        return _json_encode
    if fmt == datagen.MESSAGE_AVRO:
        encode = _avro_encoder(entity, columns)
    elif fmt == datagen.MESSAGE_PROTOBUF:
        encode = _protobuf_encoder(entity, columns)
    else:
        raise TdxError(f"unknown message format {fmt!r}")
    if not registry:
        return encode
    schema_id = register(registry, topic, fmt, schema_text(fmt, entity, columns))
    return _framed(encode, schema_id, fmt)
