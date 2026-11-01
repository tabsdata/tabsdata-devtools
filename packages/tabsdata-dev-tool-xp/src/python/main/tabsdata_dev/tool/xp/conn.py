#
# Copyright 2026 Tabsdata Inc.
#
"""Per-run interpolation and connection preparation.

A ``$secret:D<n>__KEY`` in a connection template resolves (from the backing
domain ``D<n>``'s prefixed descriptor, the environment as a fallback) to an
inline ``secret:VALUE`` and the document is piped to ``tdk collection create
--conn-file -``; nothing is written to disk. A ``${D<n>__KEY}`` -- in a template
or in a function's source -- is interpolated PLAIN, for a value that is a name,
not a credential (the D0 domain's in-system name, say).

A MySQL CDC connection gets a ``server_id`` of the run's own, whatever the
template says (`mysql_server_id`): MySQL admits one replica per id, server-wide.
"""

from __future__ import annotations

import hashlib
import os
import pathlib
import re
import shutil
from collections.abc import Callable

import yaml

from . import state
from .reporter import fs_token, rep, scratch

SECRET_RE = re.compile(r"\$secret:(.+)")  # a whole-value $secret:KEY ref
# Deliberately narrow: `${EXEC_PLAN_ID}` and friends are the file connectors'
# own destination-path tokens, substituted server-side and legal in a suite's
# function source. A reference this tool owns always names a backing domain.
VALUE_RE = re.compile(r"\$\{(D\d+__[A-Za-z_][A-Za-z0-9_]*)\}")
FILE_CONN_TYPES = ("conn.localfile:", "conn.s3:", "conn.gcs:", "conn.azureblob:")
MYSQL_CDC_TYPE = ":MySQLCdcStreamSrcConn"
# Clear of the small ids people pick by hand (the server's own is usually 1, the
# templates' 512-1012) and of the sign bit, for a client that packs it signed.
SERVER_ID_FLOOR = 1 << 24
SERVER_ID_CEIL = (1 << 31) - 1
_WIN_DRIVE_ABS_RE = re.compile(r"[A-Za-z]:[/\\]")


def interpolate(text: str, values: dict, where: str) -> str:
    """Every ``${D<n>__KEY}`` in `text` replaced by ``values[D<n>__KEY]``. An
    unknown key is a hard error: leaving the reference in place ships a literal
    ``${…}`` to a backend and fails much further away, if at all."""
    missing: list[str] = []

    def one(m: re.Match) -> str:
        key = m.group(1)
        if key not in values:
            missing.append(key)
            return m.group(0)
        return str(values[key])

    out = VALUE_RE.sub(one, text)
    if missing:
        state.die(
            f"{where}: no value for ${{{missing[0]}}} (no such key in the backing domain's descriptor)"
        )
    return out


def fn_file(functionpath: str) -> str:
    """The FILE part of ``functions/f.py::fn``."""
    return functionpath.split("::", 1)[0]


def render_function(inst, f, values: Callable[[], dict]) -> tuple[str, str | None]:
    """The ``--path`` (and ``--dir-to-bundle``) to register `f` from: the suite's
    own files when none carries a ``${KEY}``, else a RENDERED COPY under
    ``<scratch>/fn/<collection>/`` with every reference interpolated. `values` is
    a thunk because reading the descriptors costs a `domain info` per domain."""
    src = pathlib.Path(inst.source_dir)
    rel = fn_file(f.functionpath)
    selector = f.functionpath[len(rel) :]
    bundle = f.dir_to_bundle
    original = (str(src / f.functionpath), str(src / bundle) if bundle else None)
    sources = [src / rel] + (sorted((src / bundle).rglob("*.py")) if bundle else [])
    if state.run.dry_run or not any(
        VALUE_RE.search(p.read_text(encoding="utf-8")) for p in sources if p.is_file()
    ):
        return original
    dest = scratch() / "fn" / fs_token(f.collection)
    if bundle:
        shutil.copytree(
            src / bundle,
            dest / bundle,
            dirs_exist_ok=True,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
    (dest / rel).parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(src / rel, dest / rel)
    vals = values()
    rendered = [
        str(py)
        for py in sorted(dest.rglob("*.py"))
        if _replace_in_file(py, vals, f.collection)
    ]
    rep().log(
        f"interpolated ${{…}} references for collection {f.collection}",
        "\n".join(rendered),
    )
    return str(dest / rel) + selector, (str(dest / bundle) if bundle else None)


def _replace_in_file(path: pathlib.Path, values: dict, collection: str) -> bool:
    raw = path.read_text(encoding="utf-8")
    if not VALUE_RE.search(raw):
        return False
    path.write_text(
        interpolate(raw, values, f"{collection}:{path.name}"), encoding="utf-8"
    )
    return True


def _resolve_secrets(node, values: dict, tpl_name: str):
    if isinstance(node, dict):
        return {k: _resolve_secrets(v, values, tpl_name) for k, v in node.items()}
    if isinstance(node, list):
        return [_resolve_secrets(v, values, tpl_name) for v in node]
    if isinstance(node, str):
        m = SECRET_RE.fullmatch(node)
        if m:
            key = m.group(1)
            if key not in values:
                state.die(
                    f"{tpl_name}: no value for $secret:{key} (not in domain descriptor or environment)"
                )
            return f"secret:{values[key]}"
    return node


def abs_base_path(val: str) -> str:
    """Object-store connectors want ``base_path`` leading-slash absolute; domains
    export cloud paths bucket-relative, so prepend the slash. Idempotent: POSIX-
    or Windows-drive-absolute and empty values are left untouched."""
    prefix, body = "", val
    if body.startswith("secret:"):
        prefix, body = "secret:", body[len("secret:") :]
    if body and not body.startswith("/") and not _WIN_DRIVE_ABS_RE.match(body):
        body = "/" + body
    return prefix + body


def _normalize_base_paths(node) -> None:
    if isinstance(node, dict):
        for k, v in node.items():
            if k == "base_path" and isinstance(v, str):
                node[k] = abs_base_path(v)
            else:
                _normalize_base_paths(v)
    elif isinstance(node, list):
        for v in node:
            _normalize_base_paths(v)


def mysql_server_id(owner: str) -> int:
    """The replica id for the collection `owner` (``<project>/<collection>``)
    names: the same for the run's life -- a stream disabled and enabled again
    reattaches as itself -- and different from every other run's. A fixed id
    per template met the replica of a run whose failed lane kept its project:
    each attach disconnected the other (MySQL error 1236), both exited 75 and
    restarted, and neither saw a change. One in 2**31 - 2**24 ids; a hundred
    streams at once collide about once in half a million runs."""
    digest = hashlib.sha256(owner.encode()).digest()
    span = SERVER_ID_CEIL - SERVER_ID_FLOOR
    return SERVER_ID_FLOOR + int.from_bytes(digest[:8], "big") % span


def prepare_conn(
    template: pathlib.Path, descriptor: dict, owner: str | None = None
) -> str:
    """Resolve a connection template into a ready-to-create YAML doc; `owner`,
    ``<project>/<collection>``, picks a MySQL CDC connection's server id."""
    values = dict(os.environ)
    values.update({k: str(v) for k, v in descriptor.items() if v is not None})
    # On the RAW text, before parsing: a reference may be part of a longer value.
    doc = yaml.safe_load(
        interpolate(template.read_text(encoding="utf-8"), values, template.name)
    )
    doc = _resolve_secrets(doc, values, template.name)
    if any(t in str(doc.get("type", "")) for t in FILE_CONN_TYPES):
        # File connectors are single-domain; its BASE_PATH is prefixed (D0__BASE_PATH).
        base = next(
            (
                v
                for k, v in descriptor.items()
                if k == "BASE_PATH" or k.endswith("__BASE_PATH")
            ),
            None,
        )
        if base:
            doc.setdefault("spec", {})["base_path"] = base
    if owner and str(doc.get("type", "")).endswith(MYSQL_CDC_TYPE):
        doc.setdefault("spec", {})["server_id"] = mysql_server_id(owner)
    _normalize_base_paths(doc)
    return yaml.safe_dump(doc, sort_keys=False, allow_unicode=True)
