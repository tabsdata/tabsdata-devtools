#
# Copyright 2026 Tabsdata Inc.
#
"""The suite definition as pydantic models, and the Instance built from one.

A suite JSON lists ``domains`` (backend domains to create, one `tdd domain`
entry each), ``collections`` (one per connection: a connection template plus the
domains that back it, as a positional prefix map ``{"D0": …}``), ``functions``
(``functions/<file>.py::<symbol>`` relative to the suite dir) and ``triggers``.
"""

from __future__ import annotations

import json
import pathlib

from pydantic import BaseModel

from . import state, suites

CONN_FILE_SCHEME = "connection-file:"


class Domain(BaseModel):
    name: str
    system: str
    model: str | None = None
    data: str | None = None
    # Pin the BACKEND object name instead of letting create-domains derive a
    # per-run one (`xp_<user>_<ts>_<tag>_<domain>`). LAST RESORT: a pinned name
    # has no per-run uniqueness, so two instances of the suite share backend
    # objects and the second one's create fails on the first one's.
    name_in_system: str | None = None


class Collection(BaseModel):
    name: str
    type: str
    group: str
    # prefix -> domain name. Each backing domain's `meta` bag is fetched and
    # prefixed `<P>__<KEY>` so its keys never collide with another domain's.
    # Both are OMITTED for a compute-only (transformer) collection.
    domains: dict[str, str] = {}
    connection_template: str | None = None


class Function(BaseModel):
    collection: str
    functionpath: str
    dir_to_bundle: str | None = None
    # tdk's `fn register --local-pkg` is disabled upstream: a suite that sets it
    # is rejected at create-project time (bundle via `dir_to_bundle` instead).
    local_pkg: list[str] = []


class Trigger(BaseModel):
    collection: str
    function: str
    detached: bool = False


class Instance(BaseModel):
    name: str  # the instance name
    type: str  # the suite's type dir name (e.g. 'container-connectors')
    suite_file: str  # the definition, absolute
    source_dir: str  # the dir holding the definition and functions/
    base_dir: str  # the dir holding connections/
    domains: list[Domain] = []
    collections: list[Collection] = []
    functions: list[Function] = []
    triggers: list[Trigger] = []

    def domain_full(self, domain: str) -> str:
        """Instance-prefixed (actual) domain name."""
        return f"{self.name}_{domain}"

    def conn_template_path(self, ref: str) -> pathlib.Path:
        if not ref.startswith(CONN_FILE_SCHEME):
            state.die(
                f"unsupported connection_template scheme: {ref!r} (expected '{CONN_FILE_SCHEME}<path>')"
            )
        return pathlib.Path(self.base_dir) / ref[len(CONN_FILE_SCHEME) :]


def build_instance(name: str, definition: pathlib.Path) -> Instance:
    """Assemble the in-memory Instance from ONE suite definition, read live (so
    edits are always picked up). source_dir / base_dir derive from the
    definition's location, so nothing about the definition is stored in the
    instance pointer (and nothing can drift)."""
    definition = definition.resolve()
    if not definition.is_file():
        state.die(f"suite not found: {definition}")
    try:
        doc = json.loads(definition.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        state.die(f"suite {definition} is not valid JSON: {exc}")
    if not isinstance(doc, dict):
        state.die(f"suite {definition} must be a JSON object")
    source_dir = definition.parent
    return Instance(
        name=name,
        type=source_dir.name,
        suite_file=str(definition),
        source_dir=str(source_dir),
        base_dir=str(suites.base_dir(source_dir)),
        domains=doc.get("domains", []),
        collections=doc.get("collections", []),
        functions=doc.get("functions", []),
        triggers=doc.get("triggers", []),
    )
