#
# Copyright 2026 Tabsdata Inc.
#
"""The suite definition as pydantic models, and the Instance built from one.

A suite JSON is an ordered LIST of stages, run in that order by `run-suite`
(and so by one-shot), each an object holding one of:

* ``domain-manifest`` -- ``{"domains": [{name, system, model?, data?, emit?}],
  "emit_ops": FILE?}``: domains created through one `tdd domain create
  --manifest`, in parallel; each seeded domain with ``emit`` (default true)
  appends its seed's operations to a file of its own, and they are appended to
  ``emit_ops`` in the listed order once the batch is done;
* ``domains`` -- `tdd domain` calls, ``{"name", "command", "options"}`` as a
  live domain entry spells one: a domain's ``create`` (``--sys SYSTEM``) and
  then what fills it (``create-model``, ``create-data``, ...), each domain's
  calls in order and the domains side by side;
* ``collections`` -- one per connection: a connection template plus the
  domains that back it, as a positional prefix map ``{"D0": …}`` (the project
  is created before the first one);
* ``functions`` -- ``functions/<file>.py::<symbol>`` relative to the suite dir,
  registered in order, ``"enabled": false`` to register one disabled;
* ``triggers`` -- functions to fire;
* ``monitor`` -- ``{"time_out": "<VALUE><UNIT>"}``: watch the project's
  transactions until they finish, failing the run if they have not by then;
* ``live`` -- a script of named entries (`tdd domain` data verbs, pauses,
  waits, repeated nested scripts), blocking or side by side; its background
  entries keep running through the stages after it (see ``live``);
* ``sentinel`` -- latches: each holds until a key shows up in some version of
  a project table (``tdd domain sentinel-data`` wrote it at the source), or
  fails when its ``time_out`` runs out;
* ``execute`` -- python scripts in the suite dir (``scripts/``), run in order,
  each passing when it exits 0: checks a run makes of what it produced.
  ``continue_on_fail`` lets the suite go on past a failed one, still failing
  the run at its end.

A suite is resolved as it is read, for the suite run it is read for (see
``ids``): ``${xp_name(x)}`` becomes ``<XP_ID>_x`` -- how a suite names a domain
of its own run -- and ``${XP_ID}`` / ``${XP_SHORT_ID}`` the run's IDs, in every
string of it. A name written without ``${xp_name(...)}`` is FIXED: used as
written, in the tdd store and in the system. ``${XP_WORK_DIR}`` /
``${XP_PROJECT}`` in a domain call's options (a domains stage's or a live
entry's) or an execute entry's params name the run's working dir and project,
and are filled in when used (see ``work``).

A duration -- a live ``sleep``, a sentinel's ``time_out`` -- is
``"<VALUE><UNIT>"`` with unit ``s``, ``m`` or ``h`` (``"90s"``, ``"2m"``,
``"1.5h"``); a bare number is refused, since nothing says what it counts.

A stage may carry ``_``-prefixed annotations (``_comment``, ``_copyright``), and
an object holding only those is a comment.
Kinds may repeat, in any order the dependencies allow (a collection after the
domains it names, a function after its collection). The older form -- one
object with a list per kind -- is refused with what to convert it to.
"""

from __future__ import annotations

import json
import pathlib
import re
from typing import Any, ClassVar

from pydantic import (
    BaseModel,
    ConfigDict,
    ValidationError,
    model_validator,
)

from . import ids, state, suites, work

CONN_FILE_SCHEME = "connection-file:"


_DURATION = re.compile(r"^(\d+(?:\.\d+)?)\s*([smh])$")
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600}


def seconds_of(value: Any, what: str) -> float:
    """A suite duration, ``"<VALUE><UNIT>"`` (s, m, h), in seconds."""
    m = _DURATION.match(value.strip()) if isinstance(value, str) else None
    if m is None:
        raise ValueError(f"{what}: {value!r} is not <VALUE><UNIT> (units s, m, h)")
    return float(m.group(1)) * _UNIT_SECONDS[m.group(2)]


class Domain(BaseModel):
    """A suite domain, as its ``create`` call names it: what the rest of xp --
    collections, live entries, teardown, list-systems -- refers to. Not written
    in a suite; built from the domains stages' calls."""

    name: str
    system: str


def _refuse_unknown_tokens(text: str, where: str) -> None:
    bad = work.unknown(text)
    if bad:
        raise ValueError(
            f"{where}: ${{{bad[0]}}} is not a token (known: "
            + ", ".join(f"${{{t}}}" for t in work.TOKENS)
            + ")"
        )


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
    # False registers it disabled (`fn register --disabled`): a stream publisher
    # then does not start until `enable-function` -- or a later stage -- says so.
    enabled: bool = True


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
    "sentinel-data",
    "delete-data",
    "delete-model",
)
# The verbs a domains stage may run: a domain's create, then what fills it.
DOMAIN_COMMANDS = ("create", *LIVE_COMMANDS)
# Options xp sets itself on every call.
LIVE_RESERVED = {"--domain", "--domain-dir", "--format", "--latch", "--verbose", "-v"}
# ...and on create: the backend name, per run, so two runs never share one.
CREATE_RESERVED = {"--name-in-system"}
_LIVE_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class DomainCall(BaseModel):
    """One `tdd domain <command> --domain <name> <options...>`, the
    options as the words typed -- an entry of a domains stage, and what a live
    domain entry runs. A domain's ``create`` names its system with ``--sys``."""

    model_config = ConfigDict(extra="forbid")

    #: The verbs this kind of call may run.
    allowed: ClassVar[tuple[str, ...]] = DOMAIN_COMMANDS
    where: ClassVar[str] = "domains"

    name: str
    command: str
    options: list[str] = []

    @model_validator(mode="after")
    def _a_known_verb(self) -> DomainCall:
        if self.command not in self.allowed:
            raise ValueError(
                f"{self.where} command {self.command!r} is not one of {', '.join(self.allowed)}"
            )
        self.options = [str(o) for o in self.options]
        own = LIVE_RESERVED | (CREATE_RESERVED if self.command == "create" else set())
        reserved = sorted({o.split("=", 1)[0] for o in self.options} & own)
        if reserved:
            raise ValueError(
                f"{self.where} options set by xp itself: {', '.join(reserved)}"
            )
        if self.command == "create" and not self.option("--sys"):
            raise ValueError(
                f"{self.where} create of {self.name!r} needs --sys SYSTEM in its options"
            )
        for o in self.options:
            _refuse_unknown_tokens(o, f"{self.where} {self.command} on {self.name!r}")
        return self

    def has_option(self, flag: str) -> bool:
        return any(o == flag or o.startswith(flag + "=") for o in self.options)

    def option(self, flag: str) -> str | None:
        """The value given for `flag` (``--flag V`` or ``--flag=V``), if any."""
        for i, o in enumerate(self.options):
            if o == flag:
                return self.options[i + 1] if i + 1 < len(self.options) else None
            if o.startswith(flag + "="):
                return o[len(flag) + 1 :]
        return None


class LiveDomain(DomainCall):
    """A live domain entry's call: the data verbs only -- a domain's lifecycle
    (create/destroy) is xp's own."""

    allowed: ClassVar[tuple[str, ...]] = LIVE_COMMANDS
    where: ClassVar[str] = "live"


class LiveEntry(BaseModel):
    """One entry of a ``live`` script, named, in one of four kinds:

    * ``{"name", "domain": {"name", "command", "options": [...]}, "blocking"}``
      -- one `tdd domain` data verb against a suite domain;
    * ``{"name", "sleep": "<VALUE><UNIT>"}`` -- a pause;
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
    # A duration, "<VALUE><UNIT>" (see `seconds_of`). Typed loosely so a number
    # reaches that check and is refused naming the form, not as "not a string".
    sleep: Any = None
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
                ("sleep", self.sleep),
                ("wait", self.wait),
                ("live", self.live),
            )
            if v is not None
        ]
        if len(kinds) != 1:
            raise ValueError(
                f"live entry {self.name!r} needs exactly one of 'domain', 'sleep', "
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
        if self.sleep is not None:
            seconds_of(self.sleep, f"live entry {self.name!r}: sleep")
        if self.wait is not None and not self.wait:
            raise ValueError(f"live entry {self.name!r}: 'wait' names nothing")
        return self

    @property
    def kind(self) -> str:
        if self.domain is not None:
            return "domain"
        if self.sleep is not None:
            return "sleep"
        if self.wait is not None:
            return "wait"
        return "live"

    @property
    def sleep_seconds(self) -> float:
        return seconds_of(self.sleep, "sleep")

    @property
    def is_blocking(self) -> bool:
        return self.blocking is not False

    @property
    def passes(self) -> int:
        return self.repeat or 1


class Monitor(BaseModel):
    """A monitor stage: watch the project's transactions until they finish,
    for at most ``time_out`` -- given, never assumed: a watch with no end is
    what a run that hangs looks like."""

    model_config = ConfigDict(extra="forbid")

    time_out: Any  # "<VALUE><UNIT>", checked by `seconds_of` (see `sleep`)

    @model_validator(mode="after")
    def _a_duration(self) -> Monitor:
        seconds_of(self.time_out, "monitor: time_out")
        return self

    @property
    def seconds(self) -> float:
        return seconds_of(self.time_out, "time_out")


class Sentinel(BaseModel):
    """A latch: hold until ``wait_for_key`` is in some version of ``table`` in
    ``collection``, or fail once ``time_out`` has passed. Every version is
    looked at, not only the latest: a stream publisher writes each flush as a
    version of its own, holding only that flush's rows."""

    model_config = ConfigDict(extra="forbid")

    collection: str
    table: str
    wait_for_key: str
    time_out: Any  # "<VALUE><UNIT>", checked by `seconds_of` (see `sleep`)

    @model_validator(mode="after")
    def _a_duration(self) -> Sentinel:
        seconds_of(self.time_out, f"sentinel {self.wait_for_key!r}: time_out")
        return self

    @property
    def seconds(self) -> float:
        return seconds_of(self.time_out, "time_out")


_REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9._,-]+\])?$")


class Requirement(BaseModel):
    """A library an execute script needs: ``name`` (a PyPI name, extras
    allowed), ``version`` an exact pin, or absent for the latest."""

    model_config = ConfigDict(extra="forbid")

    name: str
    version: str | None = None

    @model_validator(mode="after")
    def _a_name_and_a_pin(self) -> Requirement:
        if not _REQUIREMENT_NAME.match(self.name):
            raise ValueError(f"requirement {self.name!r} is not a package name")
        if self.version is not None and not re.fullmatch(
            r"[A-Za-z0-9.+!_-]+", self.version
        ):
            raise ValueError(
                f"requirement {self.name!r}: version {self.version!r} is an exact version, "
                "e.g. 1.44.1 (not a specifier)"
            )
        return self

    @property
    def spec(self) -> str:
        return f"{self.name}=={self.version}" if self.version else self.name


class Execute(BaseModel):
    """A check script: ``py_script`` (a path in the suite dir, by convention
    under ``scripts/``) run by ``tdd _xp-execute`` -- a bare venv of its own,
    the ``tdd`` module in reach -- with ``params`` as its argv. With
    ``requirements`` it runs in a one-off venv holding them instead. Exit 0
    passes; anything else fails the step, and the run -- at once, or, with
    ``continue_on_fail``, once the suite's stages have all run."""

    model_config = ConfigDict(extra="forbid")

    name: str
    py_script: str
    params: list[str] = []
    requirements: list[Requirement] = []
    continue_on_fail: bool = False

    @model_validator(mode="after")
    def _a_script_in_the_suite(self) -> Execute:
        if not _LIVE_NAME.match(self.name):
            raise ValueError(
                f"execute name {self.name!r}: a letter, then letters, digits, '_' or '-'"
            )
        script = pathlib.PurePosixPath(self.py_script)
        if script.is_absolute() or ".." in script.parts or script.suffix != ".py":
            raise ValueError(
                f"execute {self.name!r}: py_script {self.py_script!r} must be a .py "
                "path inside the suite dir (e.g. scripts/check.py)"
            )
        self.params = [str(p) for p in self.params]
        for p in self.params:
            _refuse_unknown_tokens(p, f"execute {self.name!r}")
        return self


# A domain-manifest entry's `data` size LABEL -> `create-data --size` multiplier
# (xs=100 rows, s=1k, m=10k, l=100k, xl=1M; --size N loads N x ~100 rows).
DATA_SIZE_MULT = {"xs": 1, "s": 10, "m": 100, "l": 1000, "xl": 10000}


class ManifestDomain(BaseModel):
    """A domain as a domain-manifest stage describes it: its system and, for a
    seeded one, the model and the data size to load. ``emit`` (default true)
    says whether its seed's operations are captured -- when the stage names an
    ``emit_ops`` file at all."""

    model_config = ConfigDict(extra="forbid")

    name: str
    system: str
    model: str | None = None
    data: str | None = None
    emit: bool = True

    @model_validator(mode="after")
    def _a_known_size(self) -> ManifestDomain:
        if self.data is not None and self.data not in DATA_SIZE_MULT:
            raise ValueError(
                f"domain {self.name!r}: data {self.data!r} is not one of "
                f"{', '.join(DATA_SIZE_MULT)}"
            )
        if self.data is not None and not self.model:
            raise ValueError(f"domain {self.name!r}: data needs a model")
        return self

    @property
    def size(self) -> int:
        return DATA_SIZE_MULT[self.data or "xs"]


class DomainManifest(BaseModel):
    """A domain-manifest stage: its domains, created through one `tdd domain
    create --manifest` -- the toolkit's batch, every domain in parallel,
    heaviest backend first, chaining create -> create-model -> create-data --
    and ``emit_ops``, the file the seeds' operations end up in."""

    model_config = ConfigDict(extra="forbid")

    domains: list[ManifestDomain]
    emit_ops: str | None = None

    @model_validator(mode="after")
    def _known_tokens(self) -> DomainManifest:
        _refuse_unknown_tokens(self.emit_ops or "", "domain-manifest emit_ops")
        if not self.domains:
            raise ValueError("domain-manifest names no domains")
        return self


STAGE_KINDS = (
    "domain-manifest",
    "domains",
    "collections",
    "functions",
    "triggers",
    "monitor",
    "live",
    "sentinel",
    "execute",
)


class Stage(BaseModel):
    """One step of the suite's ordered list: its kind, and the entries of that
    kind it holds (a monitor's settings for ``monitor``)."""

    kind: str
    # Its position in the suite's list, counting comment entries: the number a
    # message names is the one a reader counts to in the file.
    at: int = 0
    domains: list[DomainCall] = []
    # The JSON key is `domain-manifest`; see stages_of.
    domain_manifest: DomainManifest | None = None
    collections: list[Collection] = []
    functions: list[Function] = []
    triggers: list[Trigger] = []
    live: list[LiveEntry] = []
    sentinel: list[Sentinel] = []
    execute: list[Execute] = []
    monitor: Monitor | None = None


class Instance(BaseModel):
    name: str  # the suite run's name
    xp_id: str = ids.PLACEHOLDER[0]
    short_id: str = ids.PLACEHOLDER[1]
    # The suite as it was read for this run: every run token resolved.
    doc: list = []
    type: str  # the suite's type dir name (e.g. 'container-connectors')
    suite_file: str  # the definition, absolute
    source_dir: str  # the dir holding the definition and functions/
    base_dir: str  # the dir holding connections/
    domains: list[Domain] = []
    collections: list[Collection] = []
    functions: list[Function] = []
    triggers: list[Trigger] = []
    live: list[LiveEntry] = []
    stages: list[Stage] = []

    @model_validator(mode="after")
    def _stages_in_dependency_order(self) -> Instance:
        """What a stage names must not come from a LATER stage: a collection's
        domains, a function's collection, a live entry's domain. A name
        defined nowhere is left to the stage that uses it, as it always was."""
        later_domains = {d.name for d in self.domains}
        later_colls = {c.name for c in self.collections}
        for stage in self.stages:
            i = stage.at
            for c in stage.collections:
                for dom in c.domains.values():
                    if dom in later_domains:
                        raise ValueError(
                            f"stage {i}: collection {c.name!r} names domain {dom!r}, created by a later stage"
                        )
            for f in stage.functions:
                if f.collection in later_colls:
                    raise ValueError(
                        f"stage {i}: function {f.functionpath!r} is in collection {f.collection!r}, created by a later stage"
                    )
            for s in stage.sentinel:
                if s.collection in later_colls:
                    raise ValueError(
                        f"stage {i}: sentinel {s.wait_for_key!r} reads collection {s.collection!r}, created by a later stage"
                    )

            def domains_of(entries: list[LiveEntry]):
                for e in entries:
                    if e.domain is not None:
                        yield e.name, e.domain.name
                    yield from domains_of(e.live or [])

            for name, dom in domains_of(stage.live):
                if dom in later_domains:
                    raise ValueError(
                        f"stage {i}: live entry {name!r} names domain {dom!r}, created by a later stage"
                    )
            later_domains -= {d.name for d in stage.domains}
            if stage.domain_manifest is not None:
                later_domains -= {d.name for d in stage.domain_manifest.domains}
            later_colls -= {c.name for c in stage.collections}
        return self

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

    @model_validator(mode="after")
    def _each_domain_created_first(self) -> Instance:
        """A domain is created once, by a domains stage, before anything else
        runs on it there; a call on a domain no create names is a typo."""
        created: set[str] = set()
        for stage in self.stages:
            for d in stage.domain_manifest.domains if stage.domain_manifest else []:
                if d.name in created:
                    raise ValueError(
                        f"stage {stage.at}: domain {d.name!r} is created twice"
                    )
                created.add(d.name)
            for call in stage.domains:
                if call.command == "create":
                    if call.name in created:
                        raise ValueError(
                            f"stage {stage.at}: domain {call.name!r} is created twice"
                        )
                    created.add(call.name)
                elif call.name not in created:
                    raise ValueError(
                        f"stage {stage.at}: {call.command} on {call.name!r} before any "
                        "create of it -- a domain's create comes first"
                    )
        return self

    @model_validator(mode="after")
    def _scripts_are_there(self) -> Instance:
        """Execute names unique across the suite, and each script present in
        the suite dir -- a missing one is found when the suite is read, not
        after the stages before it have run."""
        seen: set[str] = set()
        for stage in self.stages:
            for e in stage.execute:
                if e.name in seen:
                    raise ValueError(f"execute name {e.name!r} is used twice")
                seen.add(e.name)
                if not (pathlib.Path(self.source_dir) / e.py_script).is_file():
                    raise ValueError(
                        f"stage {stage.at}: execute {e.name!r}: no script "
                        f"{e.py_script!r} in {self.source_dir}"
                    )
        return self

    def domain(self, name: str) -> Domain:
        return next(d for d in self.domains if d.name == name)

    def system_name(self, domain: str) -> str:
        """The name a domain's container gets in its system (``--name-in-system``):
        ``<XP_SHORT_ID>_x`` for a domain of this run (``<XP_ID>_x``), a FIXED one's
        own name otherwise -- whoever fixed it knows what it is to be called."""
        prefix = f"{self.xp_id}_"
        if domain.startswith(prefix):
            return f"{self.short_id}_{domain[len(prefix) :]}"
        return domain

    def conn_template_path(self, ref: str) -> pathlib.Path:
        if not ref.startswith(CONN_FILE_SCHEME):
            state.die(
                f"unsupported connection_template scheme: {ref!r} (expected '{CONN_FILE_SCHEME}<path>')"
            )
        return pathlib.Path(self.base_dir) / ref[len(CONN_FILE_SCHEME) :]


def build_instance(
    name: str,
    definition: pathlib.Path,
    xp_id: str | None = None,
    short_id: str | None = None,
) -> Instance:
    """Assemble the in-memory Instance from ONE suite definition, read live (so
    edits are always picked up), resolved for the run `xp_id` names -- without
    one (a listing), for a placeholder run of the same shape. source_dir /
    base_dir derive from the definition's location, so nothing about the
    definition is stored in the instance pointer (and nothing can drift)."""
    definition = definition.resolve()
    if not definition.is_file():
        state.die(f"suite not found: {definition}")
    try:
        raw = json.loads(definition.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        state.die(f"suite {definition} is not valid JSON: {exc}")
    xp_id, short_id = (xp_id, short_id) if xp_id and short_id else ids.PLACEHOLDER
    try:
        doc = ids.resolve(raw, xp_id, short_id, f"suite {definition}")
    except ValueError as exc:
        state.die(str(exc))
    stages = stages_of(doc, definition)
    source_dir = definition.parent

    def every(kind: str) -> list:
        return [item for s in stages for item in s.get(kind, [])]

    try:
        return Instance(
            name=name,
            xp_id=xp_id,
            short_id=short_id,
            doc=doc if isinstance(doc, list) else [],
            type=source_dir.name,
            suite_file=str(definition),
            source_dir=str(source_dir),
            base_dir=str(suites.base_dir(source_dir)),
            domains=_created(stages),
            collections=every("collections"),
            functions=every("functions"),
            triggers=every("triggers"),
            live=every("live"),
            stages=stages,
        )
    except ValidationError as exc:
        state.die(f"suite {definition} is not a valid definition: {exc}")


def _created(stages: list[dict]) -> list[Domain]:
    """The suite's domains, in stage order: every domain-manifest entry, and one
    per ``create`` call, named and on the system its ``--sys`` says. A malformed
    entry is left to its stage's own validation."""
    out: list[Domain] = []
    for stage in stages:
        manifest = stage.get("domain_manifest")
        for raw in manifest.get("domains", []) if isinstance(manifest, dict) else []:
            if isinstance(raw, dict) and raw.get("name") and raw.get("system"):
                out.append(Domain(name=raw["name"], system=raw["system"]))
        for raw in stage.get("domains", []):
            if not isinstance(raw, dict) or raw.get("command") != "create":
                continue
            try:
                call = DomainCall(**raw)
            except ValidationError:
                continue
            out.append(Domain(name=call.name, system=call.option("--sys") or ""))
    return out


def stages_of(doc, definition: pathlib.Path) -> list[dict]:
    """The suite's stages, in order, as ``{"kind": K, K: [...]}``."""
    if isinstance(doc, dict):
        # The form every suite had before stages: named rather than left to fail
        # as "not a list", so the fix is in the message.
        state.die(
            f"suite {definition} is a single object, a form xp no longer reads: a "
            "suite is a list of stages -- "
            '[{"domains": [...]}, {"collections": [...]}, {"functions": [...]}, '
            '{"triggers": [...]}, {"monitor": {"time_out": "30m"}}] is what it ran'
        )
    if not isinstance(doc, list):
        state.die(f"suite {definition} must be a JSON list of stages")
    stages: list[dict] = []
    for i, element in enumerate(doc, 1):
        if not isinstance(element, dict):
            state.die(f"suite {definition}: stage {i} is not a JSON object")
        # `_`-prefixed keys annotate (`_comment`, `_copyright`); an object
        # holding only those is a comment.
        keys = [k for k in element if not k.startswith("_")]
        if not keys:
            continue
        if len(keys) != 1 or keys[0] not in STAGE_KINDS:
            state.die(
                f"suite {definition}: stage {i} must hold exactly one of "
                f"{', '.join(STAGE_KINDS)} (has {', '.join(keys) or 'none'})"
            )
        kind = keys[0]
        value = element[kind]
        if kind == "monitor":
            # `true` was the whole stage once; it watched for as long as it took.
            if not isinstance(value, dict) or "time_out" not in value:
                state.die(
                    f"suite {definition}: stage {i}: monitor takes "
                    '{"time_out": "<VALUE><UNIT>"}, how long it may watch (e.g. "30m")'
                )
            stages.append({"kind": kind, "at": i, "monitor": value})
        elif kind == "domain-manifest":
            # An object, not a list: its domains beside a setting of its own.
            if not isinstance(value, dict):
                state.die(
                    f"suite {definition}: stage {i}: domain-manifest takes an object "
                    '({"domains": [...], "emit_ops": FILE})'
                )
            stages.append({"kind": kind, "at": i, "domain_manifest": value})
        elif not isinstance(value, list):
            state.die(f"suite {definition}: stage {i}: {kind} takes a list")
        else:
            stages.append({"kind": kind, "at": i, kind: value})
    return stages
