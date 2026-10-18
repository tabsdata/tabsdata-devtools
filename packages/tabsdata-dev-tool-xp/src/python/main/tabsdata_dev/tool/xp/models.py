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
* ``domains`` -- `tdd domain` calls, ``{"name", "command", "options"}``: a
  domain's ``create`` (``--sys SYSTEM``) and
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
* ``actions`` -- a script of named steps (``tdd``, ``exe``, ``python``,
  ``sleep``, ``wait``) and blocks (``background``, ``parallel``, ``loop``,
  ``timeout``), tagged to be picked or skipped; every actions stage of a suite
  is one script, so a background block keeps running through the stages after
  it and a later wait finds it (see ``actions``);
* ``sentinel`` -- latches: each holds until a key shows up in some version of
  a project table (``tdd domain sentinel-data`` wrote it at the source), or
  fails when its ``time_out`` runs out;

A suite is resolved as it is read, for the suite run it is read for (see
``ids``): ``${xp:name(x)}`` becomes ``<XP_ID>_x`` -- how a suite names a domain
of its own run -- and ``${xp:id}`` / ``${xp:short_id}`` the run's IDs, in every
string of it. A name written without ``${xp:name(...)}`` is FIXED: used as
written, in the tdd store and in the system. ``${xp:dir}`` /
``${xp:project}`` in a domain call's options or an action's options and params
name the run's working dir and project, and are filled in when used (see
``work``).

A duration -- a ``sleep``'s or ``timeout``'s ``time``, a sentinel's or
monitor's ``time_out`` -- is
``"<VALUE><UNIT>"`` with unit ``s``, ``m`` or ``h`` (``"90s"``, ``"2m"``,
``"1.5h"``); a bare number is refused, since nothing says what it counts.

A stage may carry ``_``-prefixed annotations (``_comment``, ``_copyright``), and
an object holding only those is a comment. An object holding ``seq`` (a name or a
list of names) is no stage: it puts the suite's lane in those sequence groups,
beside the groups of the exclusive systems its domains are on (see ``seq``).
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
    Field,
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
    collections, teardown, list-systems -- refers to. Not written
    in a suite; built from the domains stages' calls."""

    name: str
    system: str


def _refuse_unknown_tokens(text: str, where: str, td: bool = False) -> None:
    """`td`: whether ``${td:profile}`` may stand here -- in a step's options or
    params, the arguments of a program that may call tdk."""
    misuse = work.td_misuse(text)
    if misuse is None and not td and work.TD_TOKEN_RE.search(text):
        misuse = (
            f"{work.TD_PROFILE} is for a tdd, exe or python step, which may call tdk"
        )
    if misuse:
        raise ValueError(f"{where}: {misuse}")
    bad = work.unknown(text)
    if bad:
        raise ValueError(
            f"{where}: ${{xp:{bad[0]}}} is not a token (known: "
            + ", ".join(
                f"${{xp:{t}}}" for t in (*work.TOKENS, "name(NAME)", "id", "short_id")
            )
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


# The `tdd domain` verbs that change a domain's data or model.
DATA_COMMANDS = (
    "create-model",
    "create-data",
    "modify-data",
    "sentinel-data",
    "delete-data",
    "delete-model",
)
# The verbs a domains stage may run: a domain's create, then what fills it.
DOMAIN_COMMANDS = ("create", *DATA_COMMANDS)
# Options xp sets itself on every call.
RESERVED = {"--domain", "--domain-dir", "--format", "--latch", "--verbose", "-v"}
# ...and on create: the backend name, per run, so two runs never share one.
CREATE_RESERVED = {"--name-in-system"}
_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class DomainCall(BaseModel):
    """One `tdd domain <command> --domain <name> <options...>`, the
    options as the words typed -- an entry of a domains stage. A domain's
    ``create`` names its system with ``--sys``."""

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
        own = RESERVED | (CREATE_RESERVED if self.command == "create" else set())
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


# ------------------------------------------------------------- actions ----
#: Tools `tdd` runs as shell functions, in the user's shell: `tdd-exe` cannot
#: reach them, so a step naming one could only fail when it ran.
SHELL_TOOLS = ("venv", "env", "_tdd-env")
_TAG = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*$")


class _Entry(BaseModel):
    """What every action has: a name, unique across the suite, and its tags."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    name: str
    tags: list[str] = []

    @model_validator(mode="after")
    def _a_name_and_tags(self):
        if not _NAME.match(self.name):
            raise ValueError(
                f"action name {self.name!r}: a letter, then letters, digits, '_' or '-'"
            )
        for t in self.tags:
            if not _TAG.match(t):
                raise ValueError(
                    f"action {self.name!r}: tag {t!r} is a letter, then letters, digits, '_' or '-'"
                )
        return self


class TddStep(_Entry):
    """``tdd-exe TOOL COMMAND OPTIONS...``: any of tdd's Python tools, as typed."""

    tool: str
    command: str
    options: list[str] = []
    continue_on_fail: bool = False

    @model_validator(mode="after")
    def _a_python_tool(self) -> TddStep:
        if self.tool in SHELL_TOOLS:
            raise ValueError(
                f"tdd step {self.name!r}: {self.tool!r} is a shell function of tdd, "
                "which a step cannot reach (tdd-exe runs the Python tools)"
            )
        self.options = [str(o) for o in self.options]
        for o in self.options:
            _refuse_unknown_tokens(o, f"tdd step {self.name!r}", td=True)
        return self


class ExeStep(_Entry):
    """``PROGRAM PARAMS...``: any program on the PATH -- having it is the
    suite's business."""

    program: str
    params: list[str] = []
    continue_on_fail: bool = False

    @model_validator(mode="after")
    def _a_program(self) -> ExeStep:
        if not self.program.strip():
            raise ValueError(f"exe step {self.name!r} names no program")
        self.params = [str(p) for p in self.params]
        for p in self.params:
            _refuse_unknown_tokens(p, f"exe step {self.name!r}", td=True)
        return self


class PythonStep(_Entry):
    """``uv run --no-project --with REQ... SCRIPT PARAMS...`` from the suite
    dir, on xp's own interpreter, the ``tdd`` module on its path. ``reqs`` are requirement strings, as
    uv takes them."""

    script: str
    params: list[str] = []
    reqs: list[str] = []
    continue_on_fail: bool = False

    @model_validator(mode="after")
    def _a_script_in_the_suite(self) -> PythonStep:
        script = pathlib.PurePosixPath(self.script)
        if script.is_absolute() or ".." in script.parts or script.suffix != ".py":
            raise ValueError(
                f"python step {self.name!r}: script {self.script!r} must be a .py "
                "path inside the suite dir (e.g. scripts/check.py)"
            )
        self.params = [str(p) for p in self.params]
        for p in self.params:
            _refuse_unknown_tokens(p, f"python step {self.name!r}", td=True)
        return self


class SleepStep(_Entry):
    # A duration, "<VALUE><UNIT>" (see `seconds_of`). Typed loosely so a number
    # reaches that check and is refused naming the form, not as "not a string".
    time: Any

    @model_validator(mode="after")
    def _a_duration(self) -> SleepStep:
        seconds_of(self.time, f"sleep {self.name!r}: time")
        return self

    @property
    def seconds(self) -> float:
        return seconds_of(self.time, "time")


class WaitStep(_Entry):
    for_: list[str] = Field(alias="for")

    @model_validator(mode="after")
    def _names_something(self) -> WaitStep:
        if not self.for_:
            raise ValueError(f"wait {self.name!r} names nothing to wait for")
        return self


class _Block(_Entry):
    actions: list[Action]

    @model_validator(mode="after")
    def _holds_something(self):
        if not self.actions:
            raise ValueError(f"{type(self).__name__} {self.name!r} holds no actions")
        return self


class BackgroundBlock(_Block):
    """Its actions off the main path: started, and the script goes on."""


class ParallelBlock(_Block):
    """Its actions side by side, joined at its end; ``lanes`` bounds how many
    run at once (0: all of them)."""

    lanes: int = 0

    @model_validator(mode="after")
    def _lanes(self) -> ParallelBlock:
        if self.lanes < 0:
            raise ValueError(f"parallel {self.name!r}: lanes is 0 (all) or more")
        return self


class LoopBlock(_Block):
    repeat: int

    @model_validator(mode="after")
    def _passes(self) -> LoopBlock:
        if self.repeat < 1:
            raise ValueError(f"loop {self.name!r}: repeat must be >= 1")
        return self


class TimeoutBlock(_Block):
    """Its actions for at most ``time``; then the run fails
    (``stop_on_timeout``, the default) or goes on, leaving them running."""

    time: Any
    stop_on_timeout: bool = True

    @model_validator(mode="after")
    def _a_duration(self) -> TimeoutBlock:
        seconds_of(self.time, f"timeout {self.name!r}: time")
        return self

    @property
    def seconds(self) -> float:
        return seconds_of(self.time, "time")


STEP_KINDS = ("tdd", "exe", "python", "sleep", "wait")
BLOCK_KINDS = ("background", "parallel", "loop", "timeout")


class Action(BaseModel):
    """One entry of an ``actions`` stage: exactly one of the step kinds
    (``tdd``, ``exe``, ``python``, ``sleep``, ``wait``) or the blocks
    (``background``, ``parallel``, ``loop``, ``timeout``)."""

    model_config = ConfigDict(extra="forbid")

    tdd: TddStep | None = None
    exe: ExeStep | None = None
    python: PythonStep | None = None
    sleep: SleepStep | None = None
    wait: WaitStep | None = None
    background: BackgroundBlock | None = None
    parallel: ParallelBlock | None = None
    loop: LoopBlock | None = None
    timeout: TimeoutBlock | None = None

    @model_validator(mode="after")
    def _one_kind(self) -> Action:
        kinds = [k for k in (*STEP_KINDS, *BLOCK_KINDS) if getattr(self, k) is not None]
        if len(kinds) != 1:
            raise ValueError(
                "an action is exactly one of "
                + ", ".join((*STEP_KINDS, *BLOCK_KINDS))
                + f" (has {', '.join(kinds) or 'none'})"
            )
        return self

    @property
    def kind(self) -> str:
        return next(
            k for k in (*STEP_KINDS, *BLOCK_KINDS) if getattr(self, k) is not None
        )

    @property
    def body(self):
        return getattr(self, self.kind)

    @property
    def name(self) -> str:
        return self.body.name

    @property
    def children(self) -> list[Action]:
        return self.body.actions if self.kind in BLOCK_KINDS else []


for _model in (BackgroundBlock, ParallelBlock, LoopBlock, TimeoutBlock):
    _model.model_rebuild()


class ManifestDomain(BaseModel):
    """A domain as a domain-manifest stage describes it: its system and, for a
    seeded one, the model and the size to load -- ``size`` is `create-data
    --size` itself (N loads ~N x 100 rows; default 1). ``emit`` (default true)
    says whether its seed's operations are captured -- when the stage names an
    ``emit_ops`` file at all."""

    model_config = ConfigDict(extra="forbid")

    name: str
    system: str
    model: str | None = None
    # strict: a "10" or a true is a typo, not a size.
    size: int | None = Field(default=None, strict=True)
    emit: bool = True

    @model_validator(mode="after")
    def _a_positive_size(self) -> ManifestDomain:
        if self.size is not None and self.size < 1:
            raise ValueError(
                f"domain {self.name!r}: size {self.size} is not a positive integer"
            )
        if self.size is not None and not self.model:
            raise ValueError(f"domain {self.name!r}: size needs a model")
        if self.model and self.size is None:
            self.size = 1
        return self


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
    "actions",
    "sentinel",
)
#: Stage kinds an older xp read, and what took their place.
RETIRED_KINDS = {"live": "actions", "execute": "actions"}


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
    actions: list[Action] = []
    sentinel: list[Sentinel] = []
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
    # Every actions stage's entries, in suite order: one script, as run-actions
    # runs them.
    actions: list[Action] = []
    stages: list[Stage] = []
    seq: list[str] = []

    @model_validator(mode="after")
    def _stages_in_dependency_order(self) -> Instance:
        """What a stage names must not come from a LATER stage: a collection's
        domains, a function's collection. A name defined nowhere is left to the
        stage that uses it, as it always was."""
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

            later_domains -= {d.name for d in stage.domains}
            if stage.domain_manifest is not None:
                later_domains -= {d.name for d in stage.domain_manifest.domains}
            later_colls -= {c.name for c in stage.collections}
        return self

    @model_validator(mode="after")
    def _actions_hold_together(self) -> Instance:
        """Across every actions stage, as one script: names unique; a wait
        names an entry BEFORE it, in its own list or an enclosing one -- an
        earlier stage's included, whose top level is the script's -- and not a
        sleep or a wait, which there is nothing to wait for in. A name inside
        another entry's block is out of reach (it may not have started, or may
        start again), and so is a block holding the wait (it would wait for
        itself). A bounded parallel holds no wait: lanes waiting would starve
        the lanes they wait for. A python step's script is there."""
        seen: set[str] = set()

        def walk(entries: list[Action], scope: dict[str, str], bounded: str | None):
            visible = dict(scope)
            for a in entries:
                if a.name in seen:
                    raise ValueError(f"action name {a.name!r} is used twice")
                seen.add(a.name)
                if a.kind == "wait":
                    if bounded:
                        raise ValueError(
                            f"wait {a.name!r} is inside parallel {bounded!r}, which bounds "
                            "its lanes: a lane waiting can starve the lane it waits for"
                        )
                    for ref in a.wait.for_:
                        if ref not in visible:
                            raise ValueError(
                                f"wait {a.name!r} names {ref!r}, which is not an action "
                                "before it in its own list or an enclosing one"
                            )
                        if visible[ref] in ("sleep", "wait"):
                            raise ValueError(
                                f"wait {a.name!r} names {ref!r}, a {visible[ref]}: there "
                                "is nothing in it to wait for"
                            )
                if a.kind == "python":
                    script = pathlib.Path(self.source_dir) / a.python.script
                    if not script.is_file():
                        raise ValueError(
                            f"python step {a.name!r}: no script {a.python.script!r} "
                            f"in {self.source_dir}"
                        )
                if a.children:
                    inner = bounded
                    if a.kind == "parallel" and a.parallel.lanes:
                        inner = a.name
                    walk(a.children, visible, inner)
                visible[a.name] = a.kind
            return visible

        scope: dict[str, str] = {}
        for stage in self.stages:
            scope = walk(stage.actions, scope, None)
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
    seq = seq_of(doc, definition)
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
            seq=seq,
            collections=every("collections"),
            functions=every("functions"),
            triggers=every("triggers"),
            actions=every("actions"),
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


SEQ = "seq"


def seq_of(doc, definition: pathlib.Path) -> list[str]:
    groups: list[str] = []
    for i, element in enumerate(doc if isinstance(doc, list) else [], 1):
        if not isinstance(element, dict) or SEQ not in element:
            continue
        value = element[SEQ]
        names = [value] if isinstance(value, str) else value
        if (
            not isinstance(names, list)
            or not names
            or not all(isinstance(n, str) and n.strip() for n in names)
        ):
            state.die(
                f"suite {definition}: stage {i}: seq takes a name or a list of names "
                '(e.g. {"seq": "salesforce"})'
            )
        for name in (n.strip() for n in names):
            if name not in groups:
                groups.append(name)
    return groups


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
        if not keys or keys == [SEQ]:
            continue
        if len(keys) != 1 or keys[0] not in (*STAGE_KINDS, *RETIRED_KINDS):
            state.die(
                f"suite {definition}: stage {i} must hold exactly one of "
                f"{', '.join(STAGE_KINDS)} (has {', '.join(keys) or 'none'})"
            )
        kind = keys[0]
        value = element[kind]
        if kind in RETIRED_KINDS:
            state.die(
                f"suite {definition}: stage {i}: '{kind}' is no longer read -- it is an "
                f"'{RETIRED_KINDS[kind]}' stage now (see xp's DESIGN.md, the actions stage)"
            )
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
