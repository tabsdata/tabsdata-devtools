#
# Copyright 2026 Tabsdata Inc.
#
"""The suite definition as pydantic models, and the Instance built from one.

A suite JSON lists ``domains`` (backend domains to create, one `tdd domain`
entry each), ``collections`` (one per connection: a connection template plus the
domains that back it, as a positional prefix map ``{"D0": …}``), ``functions``
(``functions/<file>.py::<symbol>`` relative to the suite dir), ``triggers`` and
``live`` -- the program of `tdd domain` data verbs `live-domains` runs against
the suite's domains once the project is up (see ``live``).
"""

from __future__ import annotations

import json
import pathlib

from pydantic import BaseModel, ValidationError, model_validator

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


# The `tdd domain` verbs a live program may run: the ones that change a domain's
# data or model, never create/destroy -- the domain's lifecycle is xp's own.
LIVE_COMMANDS = (
    "create-model",
    "create-data",
    "modify-data",
    "delete-data",
    "delete-model",
)
# Options xp sets itself on every live call.
LIVE_RESERVED = {"domain", "domain-dir", "format", "latch", "verbose"}


class LiveStep(BaseModel):
    """One step of a suite's ``live`` program, in one of three shapes:

    * a command -- ``{"command": "modify-data", "domain": "d" | ["d1", "d2"],
      "options": {"sets": 5, "ops": "Mix"}}``: `tdd domain <command> --domain
      <instance>_<d> --<option> <value>...`, one call per domain, in parallel;
    * a group -- ``{"steps": [...]}``: its steps in order;
    * a pause -- ``{"sleep": 1.5}``: seconds.

    A command or group may also carry ``repeat`` (how many times, default 1)
    and ``sleep`` (seconds between two repetitions, never after the last), so a
    group nests one loop in another.
    """

    command: str | None = None
    domain: str | list[str] | None = None
    options: dict[str, str | int | float | bool] = {}
    steps: list[LiveStep] | None = None
    repeat: int = 1
    sleep: float = 0

    @model_validator(mode="after")
    def _one_shape(self) -> LiveStep:
        if self.command is not None and self.steps is not None:
            raise ValueError("a live step is a command or a group of steps, not both")
        if self.repeat < 1:
            raise ValueError(f"repeat must be >= 1 (got {self.repeat})")
        if self.sleep < 0:
            raise ValueError(f"sleep must be >= 0 (got {self.sleep})")
        if self.command is None:
            if self.domain is not None or self.options:
                raise ValueError("'domain'/'options' belong to a step with a 'command'")
            if self.steps is None and not self.sleep:
                raise ValueError(
                    "a live step needs a 'command', 'steps' or a 'sleep' (seconds)"
                )
            return self
        if self.command not in LIVE_COMMANDS:
            raise ValueError(
                f"live command {self.command!r} is not one of {', '.join(LIVE_COMMANDS)}"
            )
        if not self.domains():
            raise ValueError(f"live command {self.command!r} needs a 'domain'")
        self.options = {
            k.lstrip("-").replace("_", "-"): v for k, v in self.options.items()
        }
        reserved = sorted(LIVE_RESERVED & self.options.keys())
        if reserved:
            raise ValueError(f"live options set by xp itself: {', '.join(reserved)}")
        return self

    def domains(self) -> list[str]:
        if self.domain is None:
            return []
        return [self.domain] if isinstance(self.domain, str) else list(self.domain)


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
    live: list[LiveStep] = []

    @model_validator(mode="after")
    def _live_domains_are_the_suites(self) -> Instance:
        known = {d.name for d in self.domains}

        def walk(steps: list[LiveStep]) -> None:
            for s in steps:
                unknown = [d for d in s.domains() if d not in known]
                if unknown:
                    raise ValueError(
                        f"live command {s.command!r} names domain(s) the suite does not define: {', '.join(unknown)}"
                    )
                walk(s.steps or [])

        walk(self.live)
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
