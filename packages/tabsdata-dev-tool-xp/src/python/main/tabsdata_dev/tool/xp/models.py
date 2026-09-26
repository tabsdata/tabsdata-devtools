#
# Copyright 2026 Tabsdata Inc.
#
"""The suite definition as pydantic models, and the Instance built from one.

A suite JSON lists ``domains`` (backend domains to create, one `tdd domain`
entry each), ``collections`` (one per connection: a connection template plus the
domains that back it, as a positional prefix map ``{"D0": …}``), ``functions``
(``functions/<file>.py::<symbol>`` relative to the suite dir), ``triggers`` and
``live`` -- the script of named entries (`tdd domain` data verbs, pauses,
waits, repeated nested scripts), blocking or side by side, that `live-domains`
runs against the suite's domains once the project is up (see ``live``).
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)

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


# The `tdd domain` verbs a live script may run: the ones that change a domain's
# data or model, never create/destroy -- the domain's lifecycle is xp's own.
LIVE_COMMANDS = (
    "create-model",
    "create-data",
    "modify-data",
    "delete-data",
    "delete-model",
)
# Options xp sets itself on every live call.
LIVE_RESERVED = {"--domain", "--domain-dir", "--format", "--latch", "--verbose", "-v"}
_LIVE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class LiveDomain(BaseModel):
    """What a domain entry runs: `tdd domain <command> --domain
    <instance>_<name> <options...>`, the options as the words typed."""

    model_config = ConfigDict(extra="forbid")

    name: str
    command: str
    options: list[str] = []

    @model_validator(mode="after")
    def _a_data_verb(self) -> LiveDomain:
        if self.command not in LIVE_COMMANDS:
            raise ValueError(
                f"live command {self.command!r} is not one of {', '.join(LIVE_COMMANDS)}"
            )
        self.options = [str(o) for o in self.options]
        reserved = sorted({o.split("=", 1)[0] for o in self.options} & LIVE_RESERVED)
        if reserved:
            raise ValueError(f"live options set by xp itself: {', '.join(reserved)}")
        return self

    def has_option(self, flag: str) -> bool:
        return any(o == flag or o.startswith(flag + "=") for o in self.options)


class LiveEntry(BaseModel):
    """One entry of a ``live`` script, named, in one of four kinds:

    * ``{"name", "domain": {"name", "command", "options": [...]}, "blocking"}``
      -- one `tdd domain` data verb against a suite domain;
    * ``{"name", "sleep_secs": N}`` -- a pause;
    * ``{"name", "wait": [NAMES]}`` -- hold until those entries have finished;
    * ``{"name", "repeat": N, "live": [...], "blocking"}`` -- a nested script,
      run N times, each pass complete when everything it started has finished.

    ``blocking`` (domain and repeat entries; default true) runs the entry to
    the end before the script goes on; false starts it and goes straight on, so
    it runs side by side with what follows until a wait names it or its
    enclosing script ends.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    domain: LiveDomain | None = None
    sleep_secs: float | None = None
    wait: list[str] | None = None
    live: list[LiveEntry] | None = None
    repeat: int | None = None
    blocking: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _one_wait_name(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("wait"), str):
            data = {**data, "wait": [data["wait"]]}
        return data

    @model_validator(mode="after")
    def _one_kind(self) -> LiveEntry:
        if not _LIVE_NAME.match(self.name):
            raise ValueError(
                f"live name {self.name!r}: a letter, then letters, digits, '_' or '-'"
            )
        kinds = [
            k
            for k, v in (
                ("domain", self.domain),
                ("sleep_secs", self.sleep_secs),
                ("wait", self.wait),
                ("live", self.live),
            )
            if v is not None
        ]
        if len(kinds) != 1:
            raise ValueError(
                f"live entry {self.name!r} needs exactly one of 'domain', 'sleep_secs', "
                f"'wait' or 'live' (has {', '.join(kinds) or 'none'})"
            )
        if self.repeat is not None and self.live is None:
            raise ValueError(f"live entry {self.name!r}: 'repeat' goes with 'live'")
        if self.repeat is not None and self.repeat < 1:
            raise ValueError(f"live entry {self.name!r}: repeat must be >= 1")
        if self.blocking is not None and self.domain is None and self.live is None:
            raise ValueError(
                f"live entry {self.name!r}: only a 'domain' or 'live' entry can be non-blocking"
            )
        if self.sleep_secs is not None and self.sleep_secs < 0:
            raise ValueError(f"live entry {self.name!r}: sleep_secs must be >= 0")
        if self.wait is not None and not self.wait:
            raise ValueError(f"live entry {self.name!r}: 'wait' names nothing")
        return self

    @property
    def kind(self) -> str:
        if self.domain is not None:
            return "domain"
        if self.sleep_secs is not None:
            return "sleep"
        if self.wait is not None:
            return "wait"
        return "live"

    @property
    def is_blocking(self) -> bool:
        return self.blocking is not False

    @property
    def passes(self) -> int:
        return self.repeat or 1


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
    live: list[LiveEntry] = []

    @model_validator(mode="after")
    def _live_script_holds_together(self) -> Instance:
        """Names unique across the whole script; a domain entry names a suite
        domain; a wait names a domain or live entry that comes BEFORE it in its
        own list or in an enclosing one -- an entry the script has started by
        the time it gets there, on the same thread. A name inside another
        entry's nested live is out of reach (it may not have started, or may
        start again), and so is an entry that contains the wait (it would
        wait for itself)."""
        known = {d.name for d in self.domains}
        seen: set[str] = set()

        def walk(entries: list[LiveEntry], scope: dict[str, str]) -> None:
            visible = dict(scope)
            for e in entries:
                if e.name in seen:
                    raise ValueError(f"live name {e.name!r} is used twice")
                seen.add(e.name)
                if e.domain is not None and e.domain.name not in known:
                    raise ValueError(
                        f"live entry {e.name!r} names domain {e.domain.name!r}, which the suite does not define"
                    )
                for ref in e.wait or []:
                    if ref not in visible:
                        raise ValueError(
                            f"live wait {e.name!r} names {ref!r}, which is not an entry before it "
                            "in its own live list or an enclosing one"
                        )
                    if visible[ref] not in ("domain", "live"):
                        raise ValueError(
                            f"live wait {e.name!r} names {ref!r}, a {visible[ref]} entry: only a "
                            "'domain' or 'live' entry runs long enough to wait for"
                        )
                if e.live is not None:
                    walk(e.live, visible)
                visible[e.name] = e.kind

        walk(self.live, {})
        return self

    def domain(self, name: str) -> Domain:
        return next(d for d in self.domains if d.name == name)

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
    try:
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
            live=doc.get("live", []),
        )
    except ValidationError as exc:
        state.die(f"suite {definition} is not a valid definition: {exc}")
