#
# Copyright 2026 Tabsdata Inc.
#

"""What a redpanda domain's topics look like: how many partitions each has,
which of them a data verb writes, and how its messages vary in shape.

Pure functions of their arguments, so a dry run plans exactly what a real one
does and a test needs no broker.

* **Partitions** (``create-model --up-to-partitions N``): the model's i-th
  entity, in model order, gets ``i mod N + 1`` partitions -- so topics side by
  side differ, and N=1 is every topic on one partition, as before. The counts
  are kept in the domain's meta as ``PARTITIONS`` (JSON), which is what a later
  reload creates the topics again from.
* **Entities** (``create-data``/``modify-data --entity A,B``): the topics a run
  writes; every other topic gets nothing, which is how a suite has a topic that
  exists and stays silent.
* **Schema changes** (``--schema-changes [KINDS]``): within each table, row j
  is left as the model made it when ``j mod (k+1) == 0`` and otherwise takes the
  ``(j mod (k+1))``-th of the k kinds chosen, in the order ``add``, ``drop``,
  ``retype``. ``add`` gives the row an ``xp_extra`` field, ``drop`` leaves its
  last field out, ``retype`` gives its first field another JSON type (a number
  becomes its string, anything else a one-element list). A changed row is what
  is produced AND what the ``--emit-ops`` trail records, so a check reads the
  messages as they were sent.
"""

from __future__ import annotations

import copy
import json

from tabsdata_dev.common.systems import constants, emit
from tabsdata_dev.common.systems.errors import TdxError

#: The meta key holding ``{entity: partitions}``.
META_PARTITIONS = "PARTITIONS"
OPT_UP_TO_PARTITIONS = "--up-to-partitions"
OPT_SCHEMA_CHANGES = "--schema-changes"

ADD, DROP, RETYPE = "add", "drop", "retype"
KINDS = (ADD, DROP, RETYPE)
#: The field an ``add`` row carries that the model does not.
EXTRA_FIELD = "xp_extra"
EXTRA_COLUMN = emit.Column(EXTRA_FIELD, "varchar(64)")


def plan_partitions(entities: list[str], up_to: int) -> dict[str, int]:
    """``{entity: partitions}``, the i-th entity getting ``i mod up_to + 1``."""
    if up_to < 1:
        raise TdxError(f"{OPT_UP_TO_PARTITIONS} must be >= 1 (got {up_to})")
    return {name: i % up_to + 1 for i, name in enumerate(entities)}


def partitions_of(meta: dict[str, str]) -> dict[str, int]:
    """The partition counts a domain recorded; ``{}`` for one created before
    they were, whose topics then all get one."""
    raw = meta.get(META_PARTITIONS, "")
    if not raw:
        return {}
    try:
        counts = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise TdxError(f"domain meta {META_PARTITIONS} is not JSON: {raw!r}") from exc
    return {str(k): int(v) for k, v in counts.items()}


def encode_partitions(counts: dict[str, int]) -> str:
    return json.dumps(counts, separators=(",", ":"))


def select_tables(tables: list[emit.Table], spec: str | None) -> list[emit.Table]:
    """The tables a ``--entity`` comma list (or ALL) names, in model order. A
    name the model does not generate is refused, naming the ones it does."""
    if not spec or spec.strip().upper() == constants.ENTITY_ALL:
        return tables
    wanted = [s.strip() for s in spec.split(",") if s.strip()]
    known = [t.name for t in tables]
    unknown = [w for w in wanted if w not in known]
    if unknown:
        raise TdxError(
            f"{constants.OPT_ENTITY}: unknown entit{'y' if len(unknown) == 1 else 'ies'} "
            f"{', '.join(unknown)} (this model produces: {', '.join(known)})"
        )
    return [t for t in tables if t.name in wanted]


def parse_kinds(spec: str | None) -> tuple[str, ...]:
    """``--schema-changes``'s kinds: none when absent, every kind for ALL (what
    the bare flag gives), else the comma list, in KINDS order."""
    if spec is None:
        return ()
    if spec.strip().upper() == constants.ENTITY_ALL:
        return KINDS
    chosen = {s.strip().lower() for s in spec.split(",") if s.strip()}
    unknown = sorted(chosen - set(KINDS))
    if unknown or not chosen:
        what = ", ".join(unknown) if unknown else repr(spec)
        raise TdxError(
            f"{OPT_SCHEMA_CHANGES}: not a kind: {what} "
            f"(kinds: {', '.join(KINDS)}, or ALL)"
        )
    return tuple(k for k in KINDS if k in chosen)


def _retyped(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return [value]
    return str(value)


def vary_row(row: dict, columns: list[emit.Column], j: int, kinds: tuple[str, ...]):
    """Row `j` of a table as ``--schema-changes`` sends it: a new dict, or the
    row itself when it is one left alone (every row, with no kinds)."""
    if not kinds:
        return row
    slot = j % (len(kinds) + 1)
    if slot == 0:
        return row
    kind = kinds[slot - 1]
    fields = [c.name for c in columns if not c.auto and c.name in row]
    out = dict(row)
    if kind == ADD:
        out[EXTRA_FIELD] = f"extra-{j}"
    elif kind == DROP and len(fields) > 1:
        out.pop(fields[-1])
    elif kind == RETYPE and fields:
        out[fields[0]] = _retyped(out[fields[0]])
    return out


def vary_tables(tables: list[emit.Table], kinds: tuple[str, ...]) -> list[emit.Table]:
    """`tables` with their rows varied (see the module docstring); a table that
    gains an ``add`` row also gains the ``xp_extra`` column, so the trail
    carries the field. The input is left as it was."""
    if not kinds:
        return tables
    out = []
    for t in tables:
        rows = [vary_row(r, t.columns, j, kinds) for j, r in enumerate(t.rows)]
        columns = list(t.columns)
        if any(EXTRA_FIELD in r for r in rows) and all(
            c.name != EXTRA_FIELD for c in columns
        ):
            columns.append(copy.copy(EXTRA_COLUMN))
        out.append(emit.Table(t.name, columns, rows, list(t.sql_post)))
    return out


def record(row: dict, columns: list[emit.Column]) -> dict:
    """The message a row is sent as: its non-auto columns in model order, those
    the row has -- a field ``drop`` left out is absent, not null."""
    return {c.name: row[c.name] for c in columns if not c.auto and c.name in row}


def message_key(row: dict, columns: list[emit.Column]) -> bytes | None:
    """The row's first field as the message key, so which partition a row lands
    on is the key's and repeats run to run. As text, so a ``retype`` row whose
    number became its string keeps its partition. ``None`` for a row without
    one."""
    for c in columns:
        if not c.auto and c.name in row:
            value = row[c.name]
            return None if value is None else str(value).encode()
    return None
