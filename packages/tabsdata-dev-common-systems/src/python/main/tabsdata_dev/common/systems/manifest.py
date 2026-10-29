#
# Copyright 2026 Tabsdata Inc.
#

"""YAML manifests for batch tdd system / tdd domain create + destroy.

A manifest is a YAML **list** of entries. A SYSTEM entry is
``{name, type, <create flags>}``; a DOMAIN entry is ``{name, sys, model?, size?,
emit-ops?}`` (its keys mirror the ``tdd domain create`` + ``create-model`` +
``create-data --size [--emit-ops FILE]`` invocations that reproduce it; ``emit-ops``
appends the load's operations to FILE, for a caller that checks them later). The domain entity prefix is deliberately NOT
recorded, so a domain manifest replays under each run's own ``d_<user>_<build>_``
prefix. Object-store / warehouse / service systems read their connection config
from the environment at create (and bake it into the descriptor), so a system
entry records only what create can't re-derive — fs's staging root and the
``--sys-hostname`` a container system advertises; secrets never enter a manifest.

``tdd system manifest`` / ``tdd domain manifest`` dump every system / domain in
the store; ``create --manifest`` replays a manifest and ``create --manifest
--sync`` reconciles the store to it (create what's missing, destroy what the
manifest omits).
"""

from __future__ import annotations

import sys
from pathlib import Path

from tabsdata_dev.common.systems import constants, descriptor
from tabsdata_dev.common.systems import systems as _systems
from tabsdata_dev.common.systems.errors import TdxError


def read(path: str) -> list[dict]:
    """Load a manifest into a list of entry mappings (``[]`` if empty). ``-`` reads
    the manifest from stdin."""
    import yaml

    if path == "-":
        # Decode the pipe ourselves: sys.stdin's encoding follows the locale, so
        # a manifest read under LANG=C would not survive a non-ASCII value.
        text = sys.stdin.buffer.read().decode("utf-8")
    else:
        try:
            text = Path(path).read_text(encoding="utf-8")
        except OSError as exc:
            raise TdxError(f"cannot read manifest {path}: {exc}")
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise TdxError(f"manifest {path} is not valid YAML: {exc}")
    if data is None:
        return []
    if not isinstance(data, list) or not all(isinstance(e, dict) for e in data):
        raise TdxError(
            f"manifest {path} must be a YAML list of entries (one mapping per "
            f"system/domain)"
        )
    return data


def write(dest: str, entries: list[dict]) -> None:
    """Write `entries` as a YAML manifest to `dest` (``-`` = stdout)."""
    import yaml

    text = yaml.safe_dump(entries, sort_keys=False, default_flow_style=False)
    if dest == "-":
        sys.stdout.write(text)
        return
    p = Path(dest)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def system_entry(info: descriptor.SystemInfo) -> dict:
    """The manifest entry that reproduces `info`: ``type`` + ``name`` plus each
    of the system's declared options. An option whose value came from an env var
    is emitted as ``<flag>$: ENV_VAR`` (the value is never written); a non-secret
    literal override is emitted as ``<flag>: value``; secrets and the
    auto-generated defaults a fresh create re-derives (a free port, a generated
    password) are omitted. A system created with ``--sys-hostname`` also records
    it (``sys-hostname: HOST``), so a replay advertises the same host."""
    entry: dict = {"name": info.name, "type": info.system}
    if info.sys_hostname:
        entry[constants.OPT_SYS_HOSTNAME.lstrip("-")] = info.sys_hostname
    backend = _systems.get(info.system)
    for opt in backend.options():
        if opt.name in info.env_refs:
            entry[f"{opt.flag}$"] = info.env_refs[opt.name]
        elif (
            opt.name in info.opt_literals and not opt.secret and info.meta.get(opt.name)
        ):
            entry[opt.flag] = info.meta[opt.name]
    return entry


def domain_entry(info: descriptor.DomainInfo) -> dict:
    """The manifest entry that reproduces `info`: its ``name`` and ``sys`` (the
    system's store name), plus ``model`` and the create-data ``size`` when seeded
    (``size`` mirrors the ``--size`` flag). The entity prefix is left out, so a
    replay creates the container under the replaying run's own
    ``d_<user>_<build>_`` prefix."""
    entry: dict = {"name": info.name, "sys": info.sys_name}
    if info.model:
        entry["model"] = info.model
    if info.data:
        entry["size"] = info.data
    # A create option a type adds: postgresnative's `--pgvector on`. Off is the
    # default, so only on is worth replaying.
    if info.meta.get("PGVECTOR") == "on":
        entry["pgvector"] = "on"
    return entry
