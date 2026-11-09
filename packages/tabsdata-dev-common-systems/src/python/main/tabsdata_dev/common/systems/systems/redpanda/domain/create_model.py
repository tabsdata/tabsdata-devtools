#
# Copyright 2026 Tabsdata Inc.
#

"""Create a model's topics in a redpanda domain, one per entity.

The shared create-model, with ``--up-to-partitions N``: the model's i-th entity
gets ``i mod N + 1`` partitions, so the topics differ from one another (1, the
default, is one partition each). The counts are recorded in the domain's meta
(``PARTITIONS``), and a create-data reload creates the topics again from them.

The entities whose messages the model makes Avro or Protobuf are recorded too
(``MESSAGE_FORMATS``), which every later produce encodes by; ``--schemas-dir
DIR`` writes each one's schema there -- ``<entity>.avsc``, ``<entity>.proto``
-- as a consumer needs it, and the report names them, with the Protobuf
message's full name.
"""

from __future__ import annotations

import argparse
import random
from pathlib import Path

from tabsdata_dev.common.systems import cli, console, datagen, descriptor
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.commands import dom_create_model
from tabsdata_dev.common.systems.systems.redpanda import shape, wire

OPT_SCHEMAS_DIR = "--schemas-dir"
_EXTENSIONS = {datagen.MESSAGE_AVRO: "avsc", datagen.MESSAGE_PROTOBUF: "proto"}


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create_model.add_arguments(parser)
    parser.add_argument(
        shape.OPT_UP_TO_PARTITIONS,
        dest="up_to_partitions",
        type=int,
        default=1,
        metavar="N",
        help="the most partitions a topic gets: the i-th entity gets i mod N + 1 "
        "(default 1, one each)",
    )
    parser.add_argument(
        OPT_SCHEMAS_DIR,
        dest="schemas_dir",
        default=None,
        metavar="DIR",
        help="write the schema of each Avro or Protobuf topic's messages to DIR "
        "(<entity>.avsc, <entity>.proto)",
    )


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    a = ctx.args
    counts = shape.plan_partitions(
        datagen.entities_of(a.model) if a.model else [], a.up_to_partitions
    )
    # In memory for the install the shared command runs; written to the
    # descriptor only once it succeeded, so a refused create-model changes nothing.
    formats = datagen.message_formats(a.model) if a.model else {}
    ctx.info.meta[shape.META_PARTITIONS] = shape.encode_partitions(counts)
    ctx.info.meta[wire.META_MESSAGE_FORMATS] = wire.encode_formats(formats)
    rc = dom_create_model.run(ctx)
    if rc == 0:
        info = descriptor.load(ctx.path)
        assert isinstance(info, descriptor.DomainInfo)
        for key in (shape.META_PARTITIONS, wire.META_MESSAGE_FORMATS):
            info.meta[key] = ctx.info.meta[key]
        descriptor.save(info, ctx.path)
        if formats:
            _report_schemas(a.model, formats, a.schemas_dir)
    return rc


def schemas(model: str, formats: dict[str, str]) -> dict[str, dict]:
    """``{entity: {format, file, message?, schema}}`` for the model's Avro and
    Protobuf entities -- the columns come from the model's own tables, as the
    messages' do."""
    tables = datagen.load_model(model).build_initial(random.Random(0), 1)
    columns = {t.name: t.columns for t in tables}
    out: dict[str, dict] = {}
    for entity, fmt in formats.items():
        if entity not in columns:
            raise TdxError(f"model '{model}' builds no table {entity}")
        entry = {
            "format": fmt,
            "file": f"{entity}.{_EXTENSIONS[fmt]}",
            "schema": wire.schema_text(fmt, entity, columns[entity]),
        }
        if fmt == datagen.MESSAGE_PROTOBUF:
            entry["message"] = f"{wire.NAMESPACE}.{wire.message_name(entity)}"
        out[entity] = entry
    return out


def _report_schemas(model: str, formats: dict[str, str], out_dir: str | None) -> None:
    found = schemas(model, formats)
    if out_dir:
        root = Path(out_dir)
        root.mkdir(parents=True, exist_ok=True)
        for entry in found.values():
            # Bytes: a schema is the same file on every platform.
            (root / entry["file"]).write_bytes(entry["schema"].encode("utf-8"))
    for entity, entry in found.items():
        where = f" -> {Path(out_dir) / entry['file']}" if out_dir else ""
        message = f" message {entry['message']}" if "message" in entry else ""
        console.out(f"  {entity}: {entry['format']}{message}{where}")
