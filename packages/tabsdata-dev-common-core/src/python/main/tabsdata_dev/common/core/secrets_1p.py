#
# Copyright 2026 Tabsdata Inc.
#

"""1Password secret provider (``secrets --set 1p:<VAULT>``).

``fetch(vault)`` reads every item in VAULT via the ``op`` CLI and returns an
ordered ``{<ITEM_TITLE>__<FIELD_ID>: <value>}`` dict for every non-null,
non-``expires`` field. Names are normalised to valid env-var names, matching the
``<PREFIX>__<KEY>`` convention a system's env-sourced options read. Prints
nothing itself — the caller renders the result to stdout.
"""

from __future__ import annotations

import json
import subprocess
from concurrent.futures import ThreadPoolExecutor

from .errors import ToolError


def _norm(s: str) -> str:
    """Uppercase, map non-``[A-Z0-9_]`` to ``_``, and prefix a leading digit with
    ``_`` so the result is a valid env-var name."""
    out = "".join(c if c.isalnum() or c == "_" else "_" for c in s.upper())
    if out and out[0].isdigit():
        out = "_" + out
    return out


def _require(cmd: str) -> None:
    if subprocess.run(["which", cmd], capture_output=True).returncode != 0:
        raise ToolError(f"'{cmd}' not found in PATH")


def fetch(vault: str) -> dict[str, str]:
    """Read every item/field in `vault` via ``op`` (items fetched concurrently),
    returning an ordered ``{<ITEM>__<FIELD>: value}`` dict. Skips null values,
    ``expires`` fields, and any item that can't be read. Prints nothing."""
    _require("op")
    cp = subprocess.run(
        ["op", "--vault", vault, "item", "list", "--format=json"],
        capture_output=True,
        encoding="utf-8",
    )
    if cp.returncode != 0:
        raise ToolError(
            f"failed to list items in vault '{vault}': "
            f"{cp.stderr.strip() or cp.stdout.strip()}"
        )
    items = json.loads(cp.stdout) if cp.stdout.strip() else []
    if not items:
        raise ToolError(f"vault '{vault}' returned no items")

    titles = [it.get("title", "") for it in items if it.get("title", "")]

    def get_item(title: str) -> dict | None:
        cp = subprocess.run(
            ["op", "--vault", vault, "item", "get", title, "--format=json"],
            capture_output=True,
            encoding="utf-8",
        )
        if cp.returncode != 0:
            return None
        return json.loads(cp.stdout)

    with ThreadPoolExecutor(max_workers=16) as executor:
        datas = list(executor.map(get_item, titles))

    secrets: dict[str, str] = {}
    for title, data in zip(titles, datas):
        if data is None:
            continue
        title_norm = _norm(data.get("title", title))
        for field in data.get("fields", []) or []:
            fid = field.get("id", "")
            if not fid or fid == "expires":
                continue
            value = field.get("value")
            if value is None:
                continue
            secrets[f"{title_norm}__{_norm(fid)}"] = str(value)
    return secrets


def read_field(vault: str, item: str, field: str) -> str:
    """One secret value, ``op read op://<vault>/<item>/<field>`` -- the way a
    personal 1Password item is read (an Employee vault's DevSecrets), as opposed
    to :func:`fetch`, which sweeps a whole shared vault."""
    _require("op")
    ref = f"op://{vault}/{item}/{field}"
    cp = subprocess.run(["op", "read", ref], capture_output=True, encoding="utf-8")
    if cp.returncode != 0:
        raise ToolError(
            f"could not read {ref}: {cp.stderr.strip() or cp.stdout.strip() or 'op failed'}"
        )
    value = cp.stdout.strip()
    if not value or value == "null":
        raise ToolError(f"{ref} is empty")
    return value


def _op(args: list[str], what: str, stdin: str | None = None) -> str:
    cp = subprocess.run(
        ["op", *args], input=stdin, capture_output=True, encoding="utf-8"
    )
    if cp.returncode != 0:
        raise ToolError(
            f"{what}: {cp.stderr.strip() or cp.stdout.strip() or 'op failed'}"
        )
    return cp.stdout


def item_exists(vault: str, title: str) -> bool:
    _require("op")
    cp = subprocess.run(
        ["op", "--vault", vault, "item", "get", title, "--format=json"],
        capture_output=True,
        encoding="utf-8",
    )
    return cp.returncode == 0


def set_item(vault: str, item: dict) -> tuple[bool, str]:
    """Put `item` in `vault` under its own title, and return
    ``(replaced, item_id)``.

    Delete first, then create: 1Password keys an item on the id *it* assigns,
    never on the title we send, so creating over a title that already exists
    makes a second item with the same name rather than replacing the first --
    and a vault with two `S3` items is one that reads back a coin toss. A
    deleted item is recoverable from Recently Deleted for 30 days, which is what
    makes delete-then-create an acceptable way to spell "set".

    The item is piped in -- ``op item create -`` reads a template from standard
    input -- so the values reach op through neither argv, which every user on the
    machine can read, nor a file.
    """
    _require("op")
    title = str(item.get("title", ""))
    replaced = item_exists(vault, title)
    if replaced:
        _op(["--vault", vault, "item", "delete", title], f"could not delete '{title}'")
    out = _op(
        ["--vault", vault, "item", "create", "-", "--format=json"],
        f"could not create '{title}'",
        stdin=json.dumps(item),
    )
    try:
        return replaced, str(json.loads(out).get("id", ""))
    except json.JSONDecodeError:
        return replaced, ""
