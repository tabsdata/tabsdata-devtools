#
# Copyright 2026 Tabsdata Inc.
#

"""1Password items for a system's credentials (``--format 1p``).

``tdd env set --secrets`` (through ``tdd _1p fetch --secrets 1p:VAULT``) reads a vault and
turn every item into ``<TITLE>__<FIELD_ID>`` environment variables -- see
``common.core.secrets_1p`` -- and those are exactly the ``$<PREFIX>__<KEY>`` names
a system's env-sourced create options read. This module writes that mapping the
other way round: from a backend to the item JSON ``op item create`` expects, so
the vault ends up holding a system's credentials in the shape ``create`` will
look for.

Both halves normalise the same way (upper-case, non-alphanumerics to ``_``), so
the round-trip is exact rather than a convention to remember:

    option ``HOSTNAME`` -> field id ``hostname`` -> ``$<TITLE>__HOSTNAME``

The **title is the env prefix**: whatever a vault item is called becomes the
``<PREFIX>`` of every variable it produces, so the default title is the
backend's ``env_prefix`` (which normalises to itself). ``--prefix`` overrides it,
for an item that already exists under a display-cased name -- ``RDSPostgres``
and ``RDSPOSTGRES`` normalise alike, so either reads back the same.

The **category** follows the fields: 1Password's ``DATABASE`` item has
``database_type``/``hostname``/``port``/``username``/``password`` built in, so a
backend whose options are that shape gets it (and the ``database_type`` menu,
filled from the SQLAlchemy dialect, since tdx knows it and the human would have
to guess 1Password's vocabulary). Everything else is an ``API_CREDENTIAL`` with
the ``expires`` field those items carry -- ``secrets_1p`` skips ``expires`` when
reading, so it never becomes a variable.
"""

from __future__ import annotations

import json

from tabsdata_dev.common.systems import options as _options

CATEGORY_DATABASE = "DATABASE"
CATEGORY_API = "API_CREDENTIAL"

TYPE_STRING = "STRING"
TYPE_CONCEALED = "CONCEALED"
TYPE_MENU = "MENU"
TYPE_DATE = "DATE"

# What a field the human still has to fill in says, as the hand-written
# templates this generates from always did.
PLACEHOLDER = "?"
# API_CREDENTIAL items carry an expiry; tdx systems do not expire.
EXPIRES_FIELD = "expires"
FAR_FUTURE = "2099-12-31"

# The options 1Password's DATABASE category has native fields for. A backend
# whose options cover them is a database item; anything else is a credential.
_DATABASE_KEYS = frozenset({"HOSTNAME", "PORT", "USERNAME", "PASSWORD"})


# What `op item create` takes, and all it takes: a title to file the item under,
# a category to shape it, and the fields. Everything else an item carries -- id,
# version, vault, timestamps, last_edited_by -- describes the item it was read
# *from*, so carrying it into a create would either be ignored or file the new
# item as a copy of the old one's identity.
UPLOAD_KEYS = ("title", "category", "fields")
# `reference` is the op:// URL a field was read at. 1Password mints it from the
# vault, item and field it ends up in, so one copied from elsewhere points at
# elsewhere.
FIELD_DROP = ("reference",)


def for_upload(item: dict) -> dict:
    """`item` reduced to what may be created from it.

    Lets a whole `op item get --format=json` be handed straight back to
    :func:`.secrets_1p.set_item`: read an item, edit a value, file it again."""
    out = {k: item[k] for k in UPLOAD_KEYS if k in item}
    out["fields"] = [
        {k: v for k, v in field.items() if k not in FIELD_DROP}
        for field in out.get("fields", [])
    ]
    return out


def vault_options(backend) -> tuple:
    """The options that belong in a shared vault: every one the backend does not
    exclude with ``onepassword_skip``.

    A local filesystem path is one machine's, never something to hand round --
    and where an option has a by-value twin (a certificate, and the file to read
    it from), an item carrying both would make every create ambiguous, since the
    backend refuses to be told the same thing twice."""
    skip = set(getattr(backend, "onepassword_skip", ()))
    return tuple(o for o in backend.options() if o.name not in skip)


def title_for(backend, override: str | None = None) -> str:
    """The item title -- which is the env prefix every field of it produces."""
    return override or getattr(backend, "env_prefix", "") or backend.slug.upper()


def category_for(backend) -> str:
    keys = {opt.name for opt in vault_options(backend)}
    return CATEGORY_DATABASE if _DATABASE_KEYS <= keys else CATEGORY_API


def dialect_of(backend) -> str:
    """The SQLAlchemy dialect, which is also 1Password's ``database_type`` menu
    vocabulary (``postgresql``, ``mysql``, ``mssql``, ``oracle``, ``db2``)."""
    return str(getattr(backend, "driver", "")).split("+", 1)[0]


def field_id(key: str) -> str:
    """The field id for a meta key. Lower-case, so it reads like the hand-written
    templates; ``secrets_1p`` upper-cases it back to the key."""
    return key.lower()


def _norm(s: str) -> str:
    """``common.core.secrets_1p._norm``, kept in step: upper-case, every
    non-alphanumeric to ``_``, a leading digit prefixed."""
    out = "".join(c if c.isalnum() or c == "_" else "_" for c in s.upper())
    if out and out[0].isdigit():
        out = "_" + out
    return out


def _blank_value(backend, opt) -> str:
    """What a field says when nothing fills it: the placeholder, unless tdx knows
    the answer. A computed default (``SYNTH``) must be written out -- left as a
    ``?``, it would be read back as the literal string ``?`` and refused at
    create, which is worse than not offering the field at all."""
    if opt.source == _options.SYNTH:
        return backend.synth_default(opt.name, backend.slug)
    return PLACEHOLDER


def fields_for(backend, values: dict[str, str] | None = None) -> list[dict[str, str]]:
    """One field per create option, in the order the backend declares them."""
    vals = values or {}
    out: list[dict[str, str]] = []
    if category_for(backend) == CATEGORY_DATABASE:
        out.append(
            {
                "id": "database_type",
                "label": "type",
                "type": TYPE_MENU,
                "value": dialect_of(backend) or PLACEHOLDER,
            }
        )
    for opt in vault_options(backend):
        fid = field_id(opt.name)
        out.append(
            {
                "id": fid,
                "label": fid,
                "type": TYPE_CONCEALED if opt.secret else TYPE_STRING,
                "value": vals.get(opt.name) or _blank_value(backend, opt),
            }
        )
    if category_for(backend) == CATEGORY_API:
        out.append(
            {
                "id": EXPIRES_FIELD,
                "label": EXPIRES_FIELD,
                "type": TYPE_DATE,
                "value": FAR_FUTURE,
            }
        )
    return out


def item(
    backend, values: dict[str, str] | None = None, title: str | None = None
) -> dict:
    """The whole item, ready for ``op item create --vault=V --template=FILE``."""
    return {
        "title": title_for(backend, title),
        "category": category_for(backend),
        "fields": fields_for(backend, values),
    }


def render(payload: dict) -> str:
    return json.dumps(payload, indent=2)


def item_for_descriptor(info, title: str | None = None) -> dict:
    """The item for a *provisioned* system: the same shape, carrying the values
    the descriptor holds rather than placeholders."""
    from tabsdata_dev.common.systems import systems as _systems

    backend = _systems.get(info.system)
    return item(backend, info.meta, title)


__all__ = [
    "CATEGORY_API",
    "CATEGORY_DATABASE",
    "for_upload",
    "item",
    "item_for_descriptor",
    "render",
    "vault_options",
]
