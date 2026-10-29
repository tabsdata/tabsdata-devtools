#
# Copyright 2026 Tabsdata Inc.
#

"""system / domain -- manager for external systems and the domains inside them.

    tdd system types                          # system types, toolsets, images
    tdd system list [--sys-dir DIR]           # systems in the store
    tdd system manifest [--out FILE]          # YAML manifest of the store
    tdd system info --sys NAME|list|ALL | --manifest FILE [--format export|unset|1p] [--prefix P]
    tdd system create  --type TYPE [--sys NAME] [--sys-prefix P] [--ports P,..] [--sys-hostname HOST]
    tdd system create  --type ALL|t1,t2 [--sys-prefix P]         # one per type
    tdd system destroy --sys NAME|s1,s2|ALL | --manifest FILE [--force] [--dry-run]
    tdd system status  --sys NAME|list|ALL | --manifest FILE
    tdd system purge   --sys NAME|list|ALL --external-prefix PREFIX [--force]
    tdd system restart --sys NAME|list|ALL | --manifest FILE
    tdd system fetch-bin [--type TYPE|t1,t2|ALL]
    tdd system connect --remote-sys [user@]HOST:PATH --remote-secret-env VAR --sys NAME
                       [--ssh-port N] [--identity KEYFILE] [--force]
    tdd system upgrade [--sys-dir DIR]        # convert legacy TDX2 descriptors
    tdd system 1p-template --type TYPE|list|ALL
    tdd system clean-docker [--yes]           # stop and delete every tdd_* docker container and volume

    tdd domain list [--domain-dir DIR]
    tdd domain manifest [--out FILE]
    tdd domain upgrade [--domain-dir DIR]
    tdd domain info --domain NAME|list|ALL | --manifest FILE [--format ...]
    tdd domain create      --sys NAME [--domain NAME] [--domain-prefix P] [--force]
    tdd domain create      --sys ALL|s1,s2 [--domain-prefix P]   # one domain / system
    tdd domain destroy     --domain NAME|d1,d2|ALL [--force] [--dry-run]
    tdd domain status      --domain NAME
    tdd domain models      --domain NAME
    tdd domain create-model --domain NAME --model MODEL
    tdd domain create-data  --domain NAME --size N [--dry-run] [--emit-ops FILE]
    tdd domain modify-data  --domain NAME --entity NAME|ALL --sets N
                            --ops Insert|Update|Delete|Mix --seed N|AUTO
                            [--dry-run] [--emit-ops FILE]  # appends JSON lines
    tdd domain sentinel-data --domain NAME --key KEY  # xp_sentinel row, stamped now
                             [--dry-run] [--emit-ops FILE]
    tdd domain delete-data  --domain NAME     # empty the model's entities, keep them
    tdd domain delete-model --domain NAME     # drop the model's entities and data

Every verb takes ``--format json|view`` and ``--verbose`` (docs/command-cli-
guidelines.md). In json the data verbs' ``ok`` event carries the per-entity
``{insert, update, delete}`` counts that ``--out json`` used to print; ``info``
carries the descriptor.

Batch: the multi-target selector is ``--type`` for a system ``create`` (one
system per type, named after it), ``--sys`` for a domain ``create`` (one domain
per system, named after it), and ``--sys`` / ``--domain`` for every other verb.
Each accepts a single name, a comma list, or ``ALL``; ``--sys-prefix P`` /
``--domain-prefix P`` prepends ``P_`` to the created name(s). Multiple targets
run in parallel, heaviest ``weight`` first (``$TDD_PARALLELISM`` bounds
concurrency), each in its own child process through ``tdd-exe``; system creates
cannot compete for ports, every type owning a fixed slot (``--ports`` pins them).
``--fail-fast`` stops on the first failure, ``--report FILE`` writes a JSON run
record and ``--brief`` prints one line per target (a failure keeps its output). ``create --manifest FILE`` replays a YAML manifest in parallel and
``--sync`` reconciles the store to it.

Toolsets: every system verb, and every domain verb of most systems, runs in the
``systems`` toolset. A backend declares the toolset its data plane needs
(``dom_toolset``) and a model may override it (``models/<model>/model.json``);
when that is not the toolset this tool runs in, ``domain`` re-dispatches the
invocation to the sibling tool registered for it (``domain-sf`` for salesforce).

The common verbs (``types`` / ``list`` / ``info`` / ``manifest`` / ``upgrade`` /
``secrets``) are handled here; everything else is *delegated* to the matching
command module -- ``systems/<slug>/<verb>.py`` for a system's own override, else
the shared implementation in ``systems/_common/commands``. A verb exists when
*some* system exposes it, so one aimed at a system that does not is rejected
naming what that system does support.

Descriptors are addressed by *name* (a file in the store dir, under
``<tdd_dir>/data/system`` / ``data/domain``) and stored encrypted (``TDX3``,
see ``crypto``). The long-running verbs accept ``--latch FILE`` to be waitable
in the background; their chatty detail goes to a ``<temp>/tdd-<tool>-...log``
while the console shows brief progress.
"""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

from tabsdata_dev.common.core import config as core_config
from tabsdata_dev.common.core import proc
from tabsdata_dev.common.systems import (
    batch,
    cli,
    console,
    constants,
    crypto,
    descriptor,
    manifest,
    shell,
    store,
    systems,
)
from tabsdata_dev.common.systems.cli import ArgumentParser
from tabsdata_dev.common.systems.errors import TdxError

# Verbs whose chatty detail is redirected to a /tmp log while the console shows
# brief progress.
LOGGED_VERBS = {
    constants.V_CREATE,
    constants.V_DESTROY,
    constants.V_PURGE,
    constants.V_STATUS,
    constants.V_RESTART,
    constants.V_CREATE_MODEL,
    constants.V_CREATE_DATA,
    constants.V_MODIFY_DATA,
    constants.V_SENTINEL_DATA,
    constants.V_DELETE_DATA,
    constants.V_DELETE_MODEL,
    constants.V_CAPTURE_TABLE,
    constants.V_RELEASE_TABLE,
}
# Verbs that accept ``--latch FILE`` (the long-running ones).
LATCH_VERBS = {
    constants.V_CREATE,
    constants.V_DESTROY,
    constants.V_PURGE,
    constants.V_CREATE_MODEL,
    constants.V_CREATE_DATA,
    constants.V_MODIFY_DATA,
    constants.V_SENTINEL_DATA,
    constants.V_DELETE_DATA,
    constants.V_DELETE_MODEL,
}
# System-tool verbs that only touch a system from the outside; every other
# delegated verb (`purge` included) reaches inside it and uses `dom_toolset`.
_SYS_PLANE_VERBS = frozenset(
    {
        constants.V_CREATE,
        constants.V_DESTROY,
        constants.V_STATUS,
        constants.V_RESTART,
        constants.V_FETCH_BIN,
        constants.V_CONNECT,
    }
)
# Verbs whose toolset a model may override (the data plane).
_MODEL_VERBS = frozenset(
    {
        constants.V_CREATE_MODEL,
        constants.V_CREATE_DATA,
        constants.V_MODIFY_DATA,
        constants.V_DELETE_DATA,
        constants.V_DELETE_MODEL,
    }
)

# ======================================================================
# Command discovery / loading -- a shared catalog gated by capability flags
# ======================================================================

_SYS_CATALOG: dict[str, tuple[str, str | None]] = {
    constants.V_CREATE: ("sys_create", None),
    constants.V_DESTROY: ("sys_destroy", None),
    constants.V_STATUS: ("sys_status", None),
    constants.V_PURGE: ("sys_purge", "supports_purge"),
    constants.V_RESTART: ("sys_restart", "supports_restart"),
    constants.V_CONNECT: ("sys_connect", "is_container"),
    # Ungated on purpose: `fetch-bin --type ALL` is the handy way to pull every
    # image at once, so a system with none warns and is skipped rather than
    # failing the run.
    constants.V_FETCH_BIN: ("sys_fetch_bin", None),
}
_DOM_CATALOG: dict[str, tuple[str, str | None]] = {
    constants.V_CREATE: ("dom_create", None),
    constants.V_DESTROY: ("dom_destroy", None),
    constants.V_STATUS: ("dom_status", None),
    constants.V_MODELS: ("dom_models", "supports_models"),
    constants.V_CREATE_MODEL: ("dom_create_model", "supports_models"),
    constants.V_CREATE_DATA: ("dom_create_data", "supports_data"),
    constants.V_MODIFY_DATA: ("dom_modify_data", "supports_changes"),
    # Gated on changes, not data: it writes one row through apply_changes, and
    # needs only the model's tables.
    constants.V_SENTINEL_DATA: ("dom_sentinel_data", "supports_changes"),
    constants.V_DELETE_DATA: ("dom_delete_data", "supports_data"),
    constants.V_DELETE_MODEL: ("dom_delete_model", "supports_models"),
    constants.V_CAPTURE_TABLE: ("dom_capture_table", "supports_table_capture"),
    constants.V_RELEASE_TABLE: ("dom_release_table", "supports_table_capture"),
}

_COMMANDS_PKG = f"{systems.__name__}._common.commands"


def verb_modules(tool: str) -> dict:
    """verb -> its command module, for the verbs that have one.

    The module declares the verb's options in `add_arguments`, which is what
    lets `config` describe them without running anything.
    """
    catalog = _DOM_CATALOG if _is_domain_tool(tool) else _SYS_CATALOG
    found = {}
    for verb, (module_name, _) in catalog.items():
        try:
            found[verb] = import_module(f"{_COMMANDS_PKG}.{module_name}")
        except ImportError:
            continue
    return found


def _is_domain_tool(tool: str) -> bool:
    return tool in (constants.DOM_TOOL, constants.DOM_SF_TOOL)


def _family(tool: str) -> str:
    """The command family a tool speaks: `domain-sf` speaks `domain`'s."""
    return constants.DOM_TOOL if _is_domain_tool(tool) else constants.SYS_TOOL


def _verb_module(verb: str) -> str:
    return verb.replace("-", "_")


def _catalog(tool: str) -> dict[str, tuple[str, str | None]]:
    return _DOM_CATALOG if _is_domain_tool(tool) else _SYS_CATALOG


def _has_verb(cls: type, cap: str | None) -> bool:
    return cap is None or bool(getattr(cls, cap, False))


def _system_verbs(tool: str, slug: str) -> list[str]:
    cls = systems.get_class(slug)
    return [v for v, (_, cap) in _catalog(tool).items() if _has_verb(cls, cap)]


def _require_verb(tool: str, slug: str, verb: str) -> None:
    _, cap = _catalog(tool)[verb]
    if _has_verb(systems.get_class(slug), cap):
        return
    raise TdxError(
        f"{tool}: system '{slug}' does not support '{verb}' "
        f"(it supports: {', '.join(_system_verbs(tool, slug))})"
    )


def _summary(module: ModuleType) -> str:
    """A verb's one-line summary, in the shape argparse help is written in: a
    lower-case fragment with no full stop, so the listing reads the same whether
    the verb is delegated or handled here.

    A module docstring is a sentence -- "Provision a system." -- and should stay
    one; this is the single place it becomes help text, so the conversion
    belongs here rather than in eighteen docstrings written for a reader of the
    module. Only an ordinary first word is lower-cased: one that keeps capitals
    of its own (`PostgreSQL`, `AWS`) is left alone.
    """
    doc = (module.__doc__ or "").strip()
    if not doc:
        return ""
    first = doc.splitlines()[0].rstrip(".")
    head = first.split(" ", 1)[0]
    if head[:1].isupper() and head[1:].islower():
        first = first[:1].lower() + first[1:]
    return first


def _command_module(tool: str, slug: str, verb: str) -> ModuleType:
    catalog = _catalog(tool)
    if verb not in catalog:
        raise TdxError(f"{tool}: system '{slug}' has no '{verb}' command")
    shared_name, _ = catalog[verb]
    base = f"{systems.__name__}.{slug}"
    if _is_domain_tool(tool):
        base += ".domain"
    for name in (f"{base}.{_verb_module(verb)}", f"{_COMMANDS_PKG}.{shared_name}"):
        try:
            module = import_module(name)
        except ModuleNotFoundError:
            continue
        if hasattr(module, "run") and hasattr(module, "add_arguments"):
            return module
    raise TdxError(f"{tool}: '{verb}' has no command module")


def _discover(tool: str) -> dict[str, str]:
    catalog = _catalog(tool)
    out: dict[str, str] = {}
    for slug in systems.all_slugs():
        cls = systems.get_class(slug)
        for verb, (_, cap) in catalog.items():
            if verb in out or not _has_verb(cls, cap):
                continue
            out[verb] = _summary(_command_module(tool, slug, verb))
    return out


def _default_slug(tool: str, verb: str) -> str:
    catalog = _catalog(tool)
    if verb not in catalog:
        raise TdxError(f"{tool}: unknown command '{verb}'")
    _, cap = catalog[verb]
    for slug in systems.all_slugs():
        if _has_verb(systems.get_class(slug), cap):
            return slug
    raise TdxError(f"{tool}: no system provides '{verb}'")


def _sole_slug() -> str:
    slugs = systems.all_slugs()
    if len(slugs) == 1:
        return slugs[0]
    raise TdxError(f"{constants.OPT_TYPE} is required (one of: {', '.join(slugs)})")


def _as_type_argv(rest: list[str]) -> str:
    out = [constants.V_CREATE]
    i = 0
    while i < len(rest):
        tok = rest[i]
        if tok == constants.OPT_SYS:
            out.append(constants.OPT_TYPE)
            if i + 1 < len(rest):
                out.append(rest[i + 1])
            i += 2
            continue
        if tok.startswith(f"{constants.OPT_SYS}="):
            out.append(f"{constants.OPT_TYPE}={tok[len(constants.OPT_SYS) + 1 :]}")
            i += 1
            continue
        out.append(tok)
        i += 1
    return " ".join(out)


def _reject_sys_batch(rest: list[str]) -> None:
    sel = cli.peek(rest, constants.OPT_SYS)
    if sel is None:
        return
    names = [n.strip() for n in sel.split(",") if n.strip()]
    if len(names) == 1 and names[0].upper() != constants.TARGET_ALL:
        return
    raise TdxError(
        f"a system {constants.V_CREATE} batches on {constants.OPT_TYPE}, not "
        f"{constants.OPT_SYS} ({constants.OPT_SYS} names a single system; nothing "
        f"exists yet to enumerate); did you mean: tdd {constants.SYS_TOOL} "
        f"{_as_type_argv(rest)}"
    )


def _system_or_none(slug: str | None):
    if not slug:
        return None
    try:
        return systems.get(slug)
    except TdxError:
        return None


# ======================================================================
# Descriptor resolution
# ======================================================================


def _load_desc(
    path: Path, role: str, name: str
) -> descriptor.SystemInfo | descriptor.DomainInfo:
    if not descriptor.is_descriptor(path):
        raise TdxError(f"no {role} named '{name}' in the store ({path})")
    info = descriptor.load(path)
    if info.role != role:
        raise TdxError(f"'{name}' is not a {role} descriptor")
    return info


def _resolve(tool: str, verb: str, rest: list[str]):
    """Pick (slug, name, info, path, store_dir) for a delegated verb, peeking raw
    argv for the target before argparse runs."""
    sys_dir = cli.peek(rest, constants.OPT_SYS_DIR)
    dom_dir = cli.peek(rest, constants.OPT_DOMAIN_DIR)
    store_dir = (
        store.domain_dir(dom_dir)
        if _is_domain_tool(tool)
        else store.system_dir(sys_dir)
    )

    if not _is_domain_tool(tool):
        if verb == constants.V_CONNECT:
            return _default_slug(tool, verb), None, None, None, store_dir
        if verb in (constants.V_CREATE, constants.V_FETCH_BIN):
            typed = cli.peek(rest, constants.OPT_TYPE)
            if typed is None and verb == constants.V_CREATE:
                _reject_sys_batch(rest)
            slug = typed or _sole_slug()
            if verb == constants.V_FETCH_BIN and (
                slug.upper() == constants.TARGET_ALL or "," in slug
            ):
                slug = _default_slug(tool, verb)
            return slug, None, None, None, store_dir
        name = cli.peek(rest, constants.OPT_SYS)
        if not name:
            raise TdxError(f"{tool} {verb}: {constants.OPT_SYS} NAME is required")
        path = store.system_path(name, sys_dir)
        info = _load_desc(path, constants.ROLE_SYSTEM, name)
        return info.system, name, info, path, store_dir

    if verb == constants.V_CREATE:
        sname = cli.peek(rest, constants.OPT_SYS)
        if not sname:
            raise TdxError(f"{tool} create: {constants.OPT_SYS} NAME is required")
        sinfo = _load_desc(
            store.system_path(sname, sys_dir), constants.ROLE_SYSTEM, sname
        )
        return sinfo.system, None, sinfo, None, store_dir
    name = cli.peek(rest, constants.OPT_DOMAIN)
    if not name:
        raise TdxError(f"{tool} {verb}: {constants.OPT_DOMAIN} NAME is required")
    path = store.domain_path(name, dom_dir)
    info = _load_desc(path, constants.ROLE_DOMAIN, name)
    return info.system, name, info, path, store_dir


# ======================================================================
# Toolset routing
# ======================================================================


def _model_toolset(model: str) -> str | None:
    """The toolset a model's data plane demands, from its optional
    ``models/<model>/model.json`` (``{"toolset": "salesforce"}``)."""
    path = Path(__file__).resolve().parent / "models" / model / "model.json"
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8")).get("toolset")
    return str(value) if value else None


def _needed_toolset(tool: str, verb: str, slug: str, info) -> str:
    inside = _is_domain_tool(tool) or verb not in _SYS_PLANE_VERBS
    if inside and verb in _MODEL_VERBS and info is not None:
        model = getattr(info, "model", None)
        override = _model_toolset(model) if model else None
        if override:
            return override
    cls = systems.get_class(slug)
    return getattr(
        cls, "dom_toolset" if inside else "sys_toolset", constants.TOOLSET_SYSTEMS
    )


def _elsewhere(tool: str, needed: str) -> str | None:
    """The sibling tool that owns toolset `needed`, or None when it is this one."""
    running = os.environ.get("_TDD_TOOL", tool)
    wanted = (
        constants.DOMAIN_TOOL_BY_TOOLSET.get(needed)
        if _is_domain_tool(tool)
        else constants.SYS_TOOL
    )
    return None if wanted is None or wanted == running else wanted


def _reroute(tool: str, verb: str, rest: list[str], needed: str) -> int | None:
    """Hand the invocation to the sibling tool of toolset `needed` when this
    tool is not it. None when this tool is the right one."""
    wanted = _elsewhere(tool, needed)
    if wanted is None:
        return None
    if not os.environ.get("TDD_DIR"):
        raise TdxError(
            f"this verb needs the '{needed}' toolset ({wanted}); run it through tdd so it "
            f"can be dispatched there"
        )
    console.debug(f"re-dispatching to {wanted} (toolset {needed})")
    rend = console.renderer()
    passthrough = [verb, *rest]
    if constants.OPT_FORMAT not in rest and not any(
        a.startswith(f"{constants.OPT_FORMAT}=") for a in rest
    ):
        passthrough += [constants.OPT_FORMAT, rend.fmt]
    console.mark_final()  # the child speaks for the run
    # Under the detail log fd 1 and 2 are the log file, so the child is handed
    # the terminal the renderer kept.
    rend.out.flush()
    rend.err.flush()
    return proc.run_tool(
        wanted, *passthrough, stdout=rend.out, stderr=rend.err
    ).returncode


# ======================================================================
# Common verbs (handled here, not delegated)
# ======================================================================


def _store_infos(store_dir: Path, role: str, *, strict: bool = False):
    if not store_dir.is_dir():
        return []
    out: list = []
    unreadable: list[str] = []
    for name in sorted(p.name for p in store_dir.iterdir() if p.is_file()):
        path = store_dir / name
        if not descriptor.is_descriptor(path):
            continue
        try:
            info = descriptor.load(path)
        except TdxError as exc:
            unreadable.append(f"  {name}: {exc}")
            continue
        if info.role == role:
            out.append(info)
    if strict and unreadable:
        raise TdxError(
            f"{len(unreadable)} descriptor(s) in {store_dir} could not be read, so "
            f"a manifest of it would be incomplete:\n" + "\n".join(unreadable)
        )
    return out


def exclusive_type(slug: str) -> bool:
    try:
        return bool(getattr(systems.get_class(slug), "exclusive", False))
    except TdxError:
        return False


def _list_store(store_dir: Path, role: str) -> None:
    rows: list[dict] = []
    if not store_dir.is_dir():
        console.result({f"{role}s": rows, "store": str(store_dir)})
        console.good(f"(no {role}s: {store_dir} does not exist)")
        return
    for name in sorted(p.name for p in store_dir.iterdir() if p.is_file()):
        path = store_dir / name
        if not descriptor.is_descriptor(path):
            continue
        try:
            info = descriptor.load(path)
        except TdxError as exc:
            console.warn(f"  {name:20} <unreadable: {exc}>")
            continue
        if info.role != role:
            continue
        row = {"name": name, "system": info.system}
        extra = ""
        if role == constants.ROLE_SYSTEM:
            row["exclusive"] = exclusive_type(info.system)
        if isinstance(info, descriptor.DomainInfo):
            row.update(model=info.model, data=info.data, sys=info.sys_name)
            extra = f"  model={info.model or '-'} data={info.data or '-'}"
        console.out(f"  {name:20} {info.system:10}{extra}")
        rows.append(row)
    console.result({f"{role}s": rows, "store": str(store_dir)})
    console.good(
        f"{len(rows)} {role}(s) in {store_dir}"
        if rows
        else f"(no {role}s in {store_dir})"
    )


def _parser_types(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_TYPES}")
    cli.add_format_verbose(p)
    return p


def _cmn_types(tool: str, rest: list[str]) -> int:
    p = _parser_types(tool)
    p.parse_args(rest)
    rows = [("TYPE", "LABEL", "WEIGHT", "SYS-TOOLSET", "DOM-TOOLSET", "IMAGE(S)")]
    types: list[dict] = []
    for slug in systems.all_slugs():
        sysobj = systems.get(slug)
        imgs = [i for i, _ in sysobj.docker_images()]
        rows.append(
            (
                slug,
                str(getattr(sysobj, "label", slug)),
                str(getattr(sysobj, "weight", 1)),
                getattr(sysobj, "sys_toolset", constants.TOOLSET_SYSTEMS),
                getattr(sysobj, "dom_toolset", constants.TOOLSET_SYSTEMS),
                ", ".join(imgs) or "-",
            )
        )
        types.append(
            {
                "type": slug,
                "label": rows[-1][1],
                "weight": int(rows[-1][2]),
                "sys_toolset": rows[-1][3],
                "dom_toolset": rows[-1][4],
                "images": imgs,
            }
        )
    widths = [max(len(r[i]) for r in rows) for i in range(5)]
    for type_, label, weight, sys_ts, dom_ts, imgs in rows:
        console.out(
            f"  {type_:<{widths[0]}}  {label:<{widths[1]}}  {weight:<{widths[2]}}  "
            f"{sys_ts:<{widths[3]}}  {dom_ts:<{widths[4]}}  {imgs}"
        )
    console.result({"types": types})
    console.good(f"{len(types)} system types")
    return 0


def _shape(fmt: str) -> str:
    """The document `--format` asks for. ``view`` and ``json`` differ in the
    envelope, not the document -- both render the payload as JSON -- so a plain
    `info` reads as it always did, and `--format json` still wraps it in events
    (the runner consumes that value before a command's parser sees it)."""
    return constants.FMT_JSON if fmt == constants.FMT_VIEW else fmt


def _parser_1p_template(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(
        prog=f"tdd {tool} {constants.V_1P_TEMPLATE}",
        description="a system type's create options as the 1Password item its "
        "credentials belong in, to fill in and push with `tdd _1p push`",
        epilog=f"example: tdd {constants.SYS_TOOL} {constants.V_1P_TEMPLATE} "
        f"{constants.OPT_TYPE} s3 | tdd _1p push --vault 1p:dev_xp --entry -",
    )
    cli.add_type(p)
    cli.add_verbose(p)
    return p


def _cmn_1p_template(tool: str, rest: list[str]) -> int:
    """A type's create options as the 1Password item its credentials belong in.

    One shape only, so there is nothing to choose: the item `op item create`
    takes and `secrets` reads back (see :mod:`.onepassword`). The title is the
    type's own env prefix, which is what the variables it yields are prefixed
    with -- renaming it would only break that."""
    from tabsdata_dev.common.systems import onepassword

    p = _parser_1p_template(tool)
    a = p.parse_args(rest)
    slugs = _template_slugs(a.type)
    items = [onepassword.item(systems.get(slug)) for slug in slugs]
    # One type is one item, as `op item create` takes it; several are a list,
    # which is a listing rather than something to file.
    text = onepassword.render(items[0] if len(items) == 1 else items)
    console.result({"types": slugs, "items": items})
    # The rendering *is* the result, on stdout, so it can be piped to `_1p push`.
    console.good(text)
    return 0


def _template_slugs(target: str | None) -> list[str]:
    """The types a `1p-template` run covers: one, a comma list, or every one of
    them (ALL). Named rather than defaulted -- a template is about a type, and
    there is no current one to assume."""
    if not target:
        raise TdxError(
            f"{constants.V_1P_TEMPLATE}: {constants.OPT_TYPE} TYPE|list|ALL is "
            f"required (see `{constants.V_TYPES}` for the types)"
        )
    if target.strip().upper() == constants.TARGET_ALL:
        return systems.all_slugs()
    slugs = [t.strip() for t in target.split(",") if t.strip()]
    for slug in slugs:
        systems.get_class(slug)  # refuses, naming every known type
    return slugs


def _parser_sys_list(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_LIST}")
    cli.add_sys_dir(p)
    cli.add_format_verbose(p)
    return p


def _cmn_sys_list(tool: str, rest: list[str]) -> int:
    p = _parser_sys_list(tool)
    a = p.parse_args(rest)
    _list_store(store.system_dir(a.sys_dir), constants.ROLE_SYSTEM)
    return 0


def _add_info_manifest(p: ArgumentParser) -> None:
    p.add_argument(
        constants.OPT_MANIFEST,
        default=None,
        metavar="FILE",
        help="show every system/domain the YAML manifest names (- = stdin)",
    )


def _info_targets(
    tool: str, target: str | None, manifest_file: str | None, dir_opt: str | None
):
    role = constants.ROLE_DOMAIN if _is_domain_tool(tool) else constants.ROLE_SYSTEM
    store_dir = (
        store.domain_dir(dir_opt)
        if _is_domain_tool(tool)
        else store.system_dir(dir_opt)
    )
    if manifest_file:
        entries = manifest.read(manifest_file)
        return [str(e["name"]) for e in entries if e.get("name")], True
    selector = constants.OPT_DOMAIN if _is_domain_tool(tool) else constants.OPT_SYS
    if not target:
        raise TdxError(
            f"{tool} {constants.V_INFO}: {selector} NAME|list|ALL or {constants.OPT_MANIFEST} FILE is required"
        )
    names = [n.strip() for n in target.split(",") if n.strip()]
    if len(names) == 1 and names[0].upper() == constants.TARGET_ALL:
        return [i.name for i in _store_infos(store_dir, role)], True
    return names, len(names) > 1


def _render_infos(
    tool: str,
    names: list[str],
    dir_opt: str | None,
    fmt: str,
    prefix: str | None,
    is_batch: bool,
    platform: str,
) -> int:
    if is_batch and prefix:
        raise TdxError(
            f"{tool} {constants.V_INFO}: {constants.OPT_PREFIX} names one backend; "
            f"a batch render prefixes each with its own name"
        )
    role = constants.ROLE_DOMAIN if _is_domain_tool(tool) else constants.ROLE_SYSTEM
    path_fn = store.domain_path if _is_domain_tool(tool) else store.system_path
    infos = [_load_desc(path_fn(name, dir_opt), role, name) for name in names]
    chunks = [
        descriptor.info_render(
            info, fmt, name.upper() if is_batch else prefix, platform
        )
        for name, info in zip(names, infos)
    ]
    text = "\n".join(chunks)
    console.result(
        {
            "as": fmt,
            "descriptors": [json.loads(i.model_dump_json()) for i in infos],
            **({"lines": text.splitlines()} if fmt != "json" else {}),
        }
    )
    # The rendering *is* the result: on stdout, as the ok message, so
    # `eval "$(tdd domain info --domain x --format export)"` keeps working.
    console.good(text)
    return 0


def _parser_sys_info(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_INFO}")
    cli.add_sys(p, required=False)
    cli.add_sys_dir(p)
    _add_info_manifest(p)
    cli.add_prefix(p)
    cli.add_platform(p)
    cli.add_format_verbose(p, constants.RENDER_FORMATS)
    return p


def _cmn_sys_info(tool: str, rest: list[str]) -> int:
    p = _parser_sys_info(tool)
    a = p.parse_args(rest)
    names, is_batch = _info_targets(tool, a.sys, a.manifest, a.sys_dir)
    return _render_infos(
        tool, names, a.sys_dir, _shape(a.format), a.prefix, is_batch, a.platform
    )


def _parser_dom_list(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_LIST}")
    cli.add_domain_dir(p)
    cli.add_format_verbose(p)
    return p


def _cmn_dom_list(tool: str, rest: list[str]) -> int:
    p = _parser_dom_list(tool)
    a = p.parse_args(rest)
    _list_store(store.domain_dir(a.domain_dir), constants.ROLE_DOMAIN)
    return 0


def _upgrade_store(store_dir: Path, role: str) -> int:
    if not store_dir.is_dir():
        console.good(f"(no {role}s: {store_dir} does not exist)")
        return 0
    converted, current, failed = 0, 0, []
    for name in sorted(p.name for p in store_dir.iterdir() if p.is_file()):
        path = store_dir / name
        if not descriptor.is_descriptor(path):
            continue
        try:
            if descriptor.upgrade(path):
                console.out(f"  {name:20} upgraded to TDX3")
                converted += 1
            else:
                current += 1
        except TdxError as exc:
            console.bad(f"  {name:20} {exc}")
            failed.append(name)
    console.result({"upgraded": converted, "current": current, "failed": failed})
    if failed:
        raise TdxError(
            f"could not upgrade {len(failed)} {role} descriptor(s): {', '.join(failed)}"
        )
    console.good(f"{converted} upgraded, {current} already current")
    return 0


def _parser_sys_upgrade(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_UPGRADE}")
    cli.add_sys_dir(p)
    cli.add_format_verbose(p)
    return p


def _cmn_sys_upgrade(tool: str, rest: list[str]) -> int:
    p = _parser_sys_upgrade(tool)
    a = p.parse_args(rest)
    return _upgrade_store(store.system_dir(a.sys_dir), constants.ROLE_SYSTEM)


def _parser_dom_upgrade(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_UPGRADE}")
    cli.add_domain_dir(p)
    cli.add_format_verbose(p)
    return p


def _cmn_dom_upgrade(tool: str, rest: list[str]) -> int:
    p = _parser_dom_upgrade(tool)
    a = p.parse_args(rest)
    return _upgrade_store(store.domain_dir(a.domain_dir), constants.ROLE_DOMAIN)


def _parser_dom_info(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_INFO}")
    cli.add_domain(p, required=False)
    cli.add_domain_dir(p)
    _add_info_manifest(p)
    cli.add_prefix(p)
    cli.add_platform(p)
    cli.add_format_verbose(p, constants.RENDER_FORMATS)
    return p


def _cmn_dom_info(tool: str, rest: list[str]) -> int:
    p = _parser_dom_info(tool)
    a = p.parse_args(rest)
    names, is_batch = _info_targets(tool, a.domain, a.manifest, a.domain_dir)
    return _render_infos(
        tool, names, a.domain_dir, _shape(a.format), a.prefix, is_batch, a.platform
    )


def _add_manifest_out(p: ArgumentParser) -> None:
    p.add_argument(
        constants.OPT_OUT,
        default="-",
        metavar="FILE",
        help="write the manifest to FILE (default: - = stdout)",
    )


def _write_manifest(tool: str, dest: str, entries: list[dict]) -> int:
    if dest == "-":
        # The manifest is the result: the ok message, on stdout.
        import yaml

        text = yaml.safe_dump(entries, sort_keys=False, default_flow_style=False)
        console.result({"entries": entries})
        console.good(text.rstrip("\n"))
        return 0
    manifest.write(dest, entries)
    console.result({"entries": entries, "out": dest})
    console.good(f"wrote {len(entries)} entries to {dest}")
    return 0


def _parser_sys_manifest(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_MANIFEST}")
    cli.add_sys_dir(p)
    _add_manifest_out(p)
    cli.add_format_verbose(p)
    return p


def _cmn_sys_manifest(tool: str, rest: list[str]) -> int:
    p = _parser_sys_manifest(tool)
    a = p.parse_args(rest)
    infos = _store_infos(
        store.system_dir(a.sys_dir), constants.ROLE_SYSTEM, strict=True
    )
    return _write_manifest(tool, a.out, [manifest.system_entry(i) for i in infos])  # type: ignore[arg-type]


def _parser_dom_manifest(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_MANIFEST}")
    cli.add_domain_dir(p)
    _add_manifest_out(p)
    cli.add_format_verbose(p)
    return p


def _cmn_dom_manifest(tool: str, rest: list[str]) -> int:
    p = _parser_dom_manifest(tool)
    a = p.parse_args(rest)
    infos = _store_infos(
        store.domain_dir(a.domain_dir), constants.ROLE_DOMAIN, strict=True
    )
    return _write_manifest(tool, a.out, [manifest.domain_entry(i) for i in infos])  # type: ignore[arg-type]


def _parser_clean_docker(tool: str) -> ArgumentParser:
    """The parser for this verb, so `config` can read its options without
    running it (see `common_parsers`)."""
    prefix = constants.DOCKER_CONTAINER_PREFIX
    p = ArgumentParser(
        prog=f"tdd {tool} {constants.V_CLEAN_DOCKER}",
        description=f"stop and delete every docker container, and every volume, whose name starts with {prefix}",
    )
    p.add_argument(
        constants.OPT_YES,
        "-y",
        action="store_true",
        help="do not ask; without it the containers and volumes are listed and a confirmation is read from the terminal (an error when there is none)",
    )
    cli.add_format_verbose(p)
    return p


def _cmn_clean_docker(tool: str, rest: list[str]) -> int:
    """Stop and delete every docker container named `tdd_*` -- the ones the
    docker-backed systems create -- and every volume named so (where systems
    keep their data), whether or not a descriptor still points at them. The
    sweep for a store that lost track of its containers, or a machine to be
    left clean. Asks first, unless --yes."""
    prefix = constants.DOCKER_CONTAINER_PREFIX
    p = _parser_clean_docker(tool)
    a = p.parse_args(rest)
    shell.require_docker()
    found = shell.list_containers(prefix)
    volumes = shell.list_volumes(prefix)
    if not found and not volumes:
        console.result({"prefix": prefix, "removed": [], "failed": []})
        console.good(f"no docker containers or volumes named {prefix}*")
        return 0
    width = max([len(c["name"]) for c in found] + [len(v) for v in volumes])
    for c in found:
        console.out(f"  {c['name']:<{width}}  {c['state']:<10} {c['image']}")
    for v in volumes:
        console.out(f"  {v:<{width}}  volume")
    what = f"{len(found)} container(s) and {len(volumes)} volume(s)"
    if not a.yes:
        if console.json_mode() or not sys.stdin.isatty():
            raise TdxError(
                f"{what} named {prefix}* would be stopped and deleted "
                f"(listed above); pass {constants.OPT_YES} to proceed"
            )
        print(
            f"stop and delete these {what}? [y/N] ",
            end="",
            file=sys.stderr,
            flush=True,
        )
        if sys.stdin.readline().strip().lower() not in ("y", "yes"):
            raise TdxError("aborted, nothing removed")
    removed: list[str] = []
    failed: list[dict] = []
    for c in found:
        try:
            if c["state"] == "running":
                shell.docker_stop(c["name"])
            shell.docker_rm(c["name"], force=True)
            removed.append(c["name"])
            console.out(f"  removed {c['name']}")
        except Exception as exc:  # noqa: BLE001 - one stubborn container must not stop the sweep
            failed.append({"name": c["name"], "error": str(exc)})
            console.warn(f"  {c['name']}: {exc}")
    # After the containers: docker refuses to remove a volume still mounted.
    for v in volumes:
        try:
            shell.docker_volume_rm(v)
            removed.append(v)
            console.out(f"  removed volume {v}")
        except Exception as exc:  # noqa: BLE001 - one stubborn volume must not stop the sweep
            failed.append({"name": v, "error": str(exc)})
            console.warn(f"  {v}: {exc}")
    console.result({"prefix": prefix, "removed": removed, "failed": failed})
    if failed:
        raise TdxError(
            f"deleted {len(removed)} container(s) and volume(s), {len(failed)} could not be removed: "
            + ", ".join(f["name"] for f in failed)
        )
    console.good(
        f"stopped and deleted {len(removed)} docker container(s) and volume(s) named {prefix}*"
    )
    return 0


#: The parser each common verb takes -- the same function its handler builds it
#: with, so `config` describes what the verb really accepts and cannot drift
#: from it. A verb handled by a command module declares its options in that
#: module's `add_arguments` instead; these are the ones handled here, which had
#: no table at all until they were reachable without running the verb.
_COMMON_PARSERS = {
    constants.SYS_TOOL: {
        constants.V_TYPES: _parser_types,
        constants.V_1P_TEMPLATE: _parser_1p_template,
        constants.V_LIST: _parser_sys_list,
        constants.V_INFO: _parser_sys_info,
        constants.V_MANIFEST: _parser_sys_manifest,
        constants.V_UPGRADE: _parser_sys_upgrade,
        constants.V_CLEAN_DOCKER: _parser_clean_docker,
    },
    constants.DOM_TOOL: {
        constants.V_TYPES: _parser_types,
        constants.V_LIST: _parser_dom_list,
        constants.V_INFO: _parser_dom_info,
        constants.V_MANIFEST: _parser_dom_manifest,
        constants.V_UPGRADE: _parser_dom_upgrade,
    },
}


def common_parsers(tool: str) -> dict:
    """verb -> a parser for it, for the verbs handled here. The twin of
    `verb_modules`, which answers the same question for the delegated ones."""
    return _COMMON_PARSERS.get(_family(tool), {})


_COMMON = {
    constants.SYS_TOOL: {
        constants.V_TYPES: _cmn_types,
        constants.V_1P_TEMPLATE: _cmn_1p_template,
        constants.V_LIST: _cmn_sys_list,
        constants.V_INFO: _cmn_sys_info,
        constants.V_MANIFEST: _cmn_sys_manifest,
        constants.V_UPGRADE: _cmn_sys_upgrade,
        constants.V_CLEAN_DOCKER: _cmn_clean_docker,
    },
    constants.DOM_TOOL: {
        constants.V_TYPES: _cmn_types,
        constants.V_LIST: _cmn_dom_list,
        constants.V_INFO: _cmn_dom_info,
        constants.V_MANIFEST: _cmn_dom_manifest,
        constants.V_UPGRADE: _cmn_dom_upgrade,
    },
}


# ======================================================================
# Batch create / destroy (operate across the whole store, not one slug)
# ======================================================================

# `emit-ops` belongs to the create-data step, not to create: every other key
# not listed here is a create flag.
_MANIFEST_KEYS = {"name", "type", "sys", "model", "size", "emit-ops"}


def _entry_option_argv(entry: dict) -> list[str]:
    argv: list[str] = []
    for key, val in entry.items():
        if key in _MANIFEST_KEYS:
            continue
        if key.endswith("$"):
            argv += [f"--{key[:-1]}:env", str(val)]
        else:
            argv += [f"--{key}", str(val)]
    return argv


def _store_dir_argv(tool: str, store_dir_opt: str | None) -> list[str]:
    if not store_dir_opt:
        return []
    flag = constants.OPT_DOMAIN_DIR if _is_domain_tool(tool) else constants.OPT_SYS_DIR
    return [flag, store_dir_opt]


def _entry_steps(
    tool: str,
    entry: dict,
    *,
    force: bool,
    store_dir_opt: str | None = None,
) -> list[list[str]]:
    if "name" not in entry:
        raise TdxError(f"manifest entry has no 'name': {entry}")
    name = str(entry["name"])
    f = [constants.OPT_FORCE] if force else []
    d = _store_dir_argv(tool, store_dir_opt)
    if not _is_domain_tool(tool):
        return [
            [
                constants.V_CREATE,
                constants.OPT_TYPE,
                str(entry["type"]),
                constants.OPT_SYS,
                name,
                *d,
                *f,
                *_entry_option_argv(entry),
            ]
        ]
    steps = [
        [
            constants.V_CREATE,
            constants.OPT_SYS,
            str(entry["sys"]),
            constants.OPT_DOMAIN,
            name,
            *d,
            *f,
            *_entry_option_argv(entry),
        ]
    ]
    if entry.get("model"):
        steps.append(
            [
                constants.V_CREATE_MODEL,
                constants.OPT_DOMAIN,
                name,
                constants.OPT_MODEL,
                str(entry["model"]),
                *d,
                *f,
            ]
        )
    if entry.get("size"):
        # No force here: a forced create-data drops and recreates the tables,
        # and with a model the step before has just installed them empty.
        data_force = [] if entry.get("model") else f
        steps.append(
            [
                constants.V_CREATE_DATA,
                constants.OPT_DOMAIN,
                name,
                constants.OPT_SIZE,
                str(entry["size"]),
                *(
                    [constants.OPT_EMIT_OPS, str(entry["emit-ops"])]
                    if entry.get("emit-ops")
                    else []
                ),
                *d,
                *data_force,
            ]
        )
    return steps


def _entry_weight(tool: str, entry: dict) -> int:
    if not _is_domain_tool(tool):
        return batch.weight_for(str(entry.get("type", "")))
    return batch.weight_of_stored(constants.ROLE_SYSTEM, str(entry.get("sys", "")))


def _store_names(tool: str, store_dir_opt: str | None) -> set[str]:
    if not _is_domain_tool(tool):
        return {
            i.name
            for i in _store_infos(
                store.system_dir(store_dir_opt), constants.ROLE_SYSTEM
            )
        }
    return {
        i.name
        for i in _store_infos(store.domain_dir(store_dir_opt), constants.ROLE_DOMAIN)
    }


def _create_from_manifest(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_CREATE}")
    p.add_argument(
        constants.OPT_MANIFEST,
        required=True,
        metavar="FILE",
        help="create every entry in the YAML manifest (- = stdin)",
    )
    p.add_argument(
        constants.OPT_SYNC,
        action="store_true",
        help="reconcile: also destroy store entries the manifest omits",
    )
    cli.add_force(p)
    cli.add_report(p)
    cli.add_fail_fast(p)
    cli.add_brief(p)
    if not _is_domain_tool(tool):
        cli.add_sys_hostname(p)
    dir_opt = _add_store_dir(tool, p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    hostname = (
        cli.parse_hostname(a.sys_hostname) if getattr(a, "sys_hostname", None) else ""
    )
    store_dir_opt = getattr(a, dir_opt)
    entries = manifest.read(a.manifest)
    existing = _store_names(tool, store_dir_opt)
    manifest_names = {str(e["name"]) for e in entries if "name" in e}

    to_create: list[dict] = []
    unchanged = 0
    for entry in entries:
        name = str(entry.get("name", ""))
        if name in existing and a.sync and not a.force:
            console.out(f"  = {name} (present, left unchanged)")
            unchanged += 1
        else:
            to_create.append(entry)

    tasks: list[batch.Task] = []
    build_failed = 0
    for entry in to_create:
        if hostname:
            entry = {**entry, constants.OPT_SYS_HOSTNAME.lstrip("-"): hostname}
        try:
            steps = _entry_steps(
                tool, entry, force=a.force, store_dir_opt=store_dir_opt
            )
        except (TdxError, KeyError) as exc:
            console.bad(f"  ! {entry.get('name', entry)}: {exc}")
            build_failed += 1
            continue
        tasks.append(batch.Task(str(entry["name"]), _entry_weight(tool, entry), steps))

    # Several stages may follow, so the batches do not emit the run's summary;
    # this function does, once.
    rc = (
        batch.execute(
            tool,
            constants.V_CREATE,
            tasks,
            report_path=a.report,
            fail_fast=a.fail_fast,
            brief=a.brief,
            final=False,
        )
        if tasks
        else 0
    )
    omitted: list[str] = []
    if a.sync:
        omitted = sorted(existing - manifest_names)
        if omitted:
            selector = (
                constants.OPT_DOMAIN if _is_domain_tool(tool) else constants.OPT_SYS
            )
            rc = (
                batch.run(
                    tool,
                    constants.V_DESTROY,
                    [
                        selector,
                        ",".join(omitted),
                        *_store_dir_argv(tool, store_dir_opt),
                        constants.OPT_FORCE,
                    ],
                    final=False,
                )
                or rc
            )
    console.result(
        {
            "created": [t.name for t in tasks if t.status == "ok"],
            "failed": [t.name for t in tasks if t.status == "fail"],
            "unchanged": unchanged,
            "destroyed": omitted,
        }
    )
    rc = rc or (1 if build_failed else 0)
    if rc:
        raise TdxError(
            f"manifest {constants.V_CREATE}: {sum(1 for t in tasks if t.status == 'fail') + build_failed} entr(y/ies) failed"
        )
    console.good(
        f"manifest: {len(tasks)} created, {unchanged} unchanged"
        + (f", {len(omitted)} destroyed" if omitted else "")
    )
    return 0


def _drop_flag(argv: list[str], flag: str) -> list[str]:
    out: list[str] = []
    i = 0
    while i < len(argv):
        if argv[i] == flag:
            i += 2
            continue
        if argv[i].startswith(f"{flag}="):
            i += 1
            continue
        out.append(argv[i])
        i += 1
    return out


def _verb_from_manifest(tool: str, verb: str, rest: list[str]) -> int:
    entries = manifest.read(cli.peek(rest, constants.OPT_MANIFEST) or "")
    names = [str(e["name"]) for e in entries if e.get("name")]
    role = "domains" if _is_domain_tool(tool) else "systems"
    if not names:
        console.good(f"manifest lists no {role} to {verb}")
        return 0
    selector = constants.OPT_DOMAIN if _is_domain_tool(tool) else constants.OPT_SYS
    new_rest = _drop_flag(rest, constants.OPT_MANIFEST) + [selector, ",".join(names)]
    return batch.run(tool, verb, new_rest, check=_check_child(tool))


_MANIFEST_VERBS = {
    constants.V_DESTROY,
    constants.V_RESTART,
    constants.V_PURGE,
    constants.V_STATUS,
}
_STORE_READING_VERBS = {
    constants.V_LIST,
    constants.V_INFO,
    constants.V_MANIFEST,
    constants.V_UPGRADE,
}


def _maybe_batch(tool: str, verb: str, rest: list[str]) -> int | None:
    if verb == constants.V_CREATE and cli.peek(rest, constants.OPT_MANIFEST):
        return _create_from_manifest(tool, rest)
    if verb in _MANIFEST_VERBS and cli.peek(rest, constants.OPT_MANIFEST):
        return _verb_from_manifest(tool, verb, rest)
    if batch.is_batch(tool, verb, rest):
        return batch.run(tool, verb, rest, check=_check_child(tool))
    return None


def _check_child(tool: str):
    """What a batch parent runs on each child's argv before any child starts:
    parse it with the parser that child will build, so an option no target
    takes -- or a bad value -- is one error up front rather than the same
    failure once per target after the batch has begun.

    The parse needs the target's type, and only a stored target has one: a
    target that is not in the store, a verb its type does not have, or a type
    whose verb lives in another toolset (its module may not import here) is
    left to its child, which reports it as it always has -- per target, so an
    `ALL` batch still runs the targets that can.
    """

    def check(argv: list[str]) -> None:
        verb, rest = argv[0], argv[1:]
        try:
            slug, _, info, _, _ = _resolve(tool, verb, rest)
            _require_verb(tool, slug, verb)
        except TdxError:
            return
        if _elsewhere(tool, _needed_toolset(tool, verb, slug, info)) is not None:
            return
        _verb_parser(tool, verb, slug, info)[0].parse_args(rest)

    return check


# ======================================================================
# Dispatch
# ======================================================================


def _add_store_dir(tool: str, p: ArgumentParser) -> str:
    if not _is_domain_tool(tool):
        cli.add_sys_dir(p)
        return "sys_dir"
    cli.add_domain_dir(p)
    return "domain_dir"


#: What each tool of the family is, in one line -- the description argparse puts
#: under the usage, the way every other command has one.
DESCRIPTIONS = {
    constants.SYS_TOOL: (
        "manage external systems for testing: databases, object stores, "
        "services (docker, cloud, remote)"
    ),
    constants.DOM_TOOL: (
        "manage domains inside systems: schemas, generated data, change sets"
    ),
    constants.DOM_SF_TOOL: (
        "manage domains inside systems: schemas, generated data, change sets "
        "(the salesforce data plane)"
    ),
}


def top_help(tool: str) -> tuple[str, dict]:
    """The tool's help: text for view, and the same as fields for json."""
    family = _family(tool)
    common = _COMMON[family]
    delegated = _discover(tool)
    verbs = list(common) + [v for v in delegated if v not in common]
    summaries = {
        constants.V_TYPES: "list system types, their toolsets and docker images",
        constants.V_1P_TEMPLATE: "a type's create options as a 1Password item (--type T)",
        constants.V_LIST: "list the descriptors in the store",
        constants.V_INFO: "print a descriptor (--format export|unset|1p)",
        constants.V_MANIFEST: "dump a YAML manifest of the store (--out FILE)",
        constants.V_UPGRADE: "convert legacy TDX2 descriptors in the store to TDX3",
        constants.V_CLEAN_DOCKER: f"stop and delete every {constants.DOCKER_CONTAINER_PREFIX}* docker container (--yes/-y to skip the prompt)",
    }
    summaries.update(delegated)
    # `config` is every command's, from the shared layer rather than this table.
    verbs.append(constants.V_CONFIG)
    summaries[constants.V_CONFIG] = core_config.SUMMARY
    # Laid out by argparse, not by hand: this family builds a parser per verb
    # rather than one with subparsers, so its help was written out line by line
    # and drifted from every other command's -- a different usage line, no
    # `options:` section at all. A throwaway parser carrying the same verbs and
    # the same shared options produces the shape argparse gives `tdd gsx`, from
    # the one formatter, so the two cannot read differently again.
    import argparse

    from tabsdata_dev.common.core import cli as core_cli

    epilog = "\n".join(
        [
            "environment:",
            *(
                f"  {ev.name:24} {ev.help} [default: {ev.default}]"
                for ev in constants.ENV_VARS
            ),
            "",
            f"store: {store.system_dir()}",
            f"       {store.domain_dir()}",
            (
                f"       (--sys-dir / --domain-dir, else ${constants.ENV_SYSTEM_DIR} / "
                f"${constants.ENV_DOMAIN_DIR}, override)"
            ),
        ]
    )
    p = core_cli.parser(tool, DESCRIPTIONS[tool])
    p.epilog = epilog
    p.formatter_class = argparse.RawDescriptionHelpFormatter
    subs = p.add_subparsers(dest="verb", metavar="SUBCOMMAND")
    for verb in verbs:
        subs.add_parser(verb, help=summaries.get(verb, ""))
    lines = [p.format_help().rstrip("\n")]
    fields = {
        "commands": [{"name": v, "summary": summaries.get(v, "")} for v in verbs],
        "environment": [
            {"name": ev.name, "default": ev.default, "help": ev.help}
            for ev in constants.ENV_VARS
        ],
        "store": {"system": str(store.system_dir()), "domain": str(store.domain_dir())},
    }
    return "\n".join(lines), fields


def dispatch(tool: str, argv: list[str]) -> int:
    """Run one invocation of `tool` (already bound to a renderer). Returns the
    exit code; raises TdxError / UsageError for the runner to render."""
    family = _family(tool)
    verb, rest = argv[0], argv[1:]
    common = _COMMON[family]
    if verb in common:
        if verb in _STORE_READING_VERBS and not any(
            a in constants.HELP_FLAGS for a in rest
        ):
            crypto.require_secret()
        return common[verb](tool, rest)
    if verb not in _discover(tool):
        raise TdxError(f"{tool}: unknown command '{verb}' (try `tdd {tool} -h`)")
    wants_help = any(a in constants.HELP_FLAGS for a in rest)
    if wants_help:
        _help_parser(tool, verb, rest).parse_args(rest)  # prints help and exits
        return 0
    batched = _maybe_batch(tool, verb, rest)
    if batched is not None:
        return batched
    slug, name, info, path, store_dir = _resolve(tool, verb, rest)
    _require_verb(tool, slug, verb)
    rerouted = _reroute(tool, verb, rest, _needed_toolset(tool, verb, slug, info))
    if rerouted is not None:
        return rerouted
    p, system, module = _verb_parser(tool, verb, slug, info)
    args = p.parse_args(rest)
    ctx = cli.Context(family, verb, slug, system, args, name, info, path, store_dir)
    return module.run(ctx) or 0


def _help_parser(tool: str, verb: str, rest: list[str]) -> ArgumentParser:
    """The parser `-h` prints. A type can add options to a verb (postgresnative's
    ``domain create --pgvector``, redpanda's), so a named target -- ``--sys``,
    ``--domain``, ``--type`` on a system create -- gets its own type's parser,
    bound as the run binds it. Help needs no key and no target, though: one the
    store lacks or cannot read, a batch, or none at all falls back to the first
    type with the verb."""
    if verb == constants.V_CREATE and _family(tool) == constants.SYS_TOOL:
        named_type = cli.peek(rest, constants.OPT_TYPE)
        return _unbound_parser(
            tool, verb, named_type or _default_slug(tool, verb), named_type
        )
    try:
        slug, _, info, _, _ = _resolve(tool, verb, rest)
        _require_verb(tool, slug, verb)
        return _verb_parser(tool, verb, slug, info)[0]
    except TdxError:
        slug = _default_slug(tool, verb)
        return _unbound_parser(tool, verb, slug, slug)


def _unbound_parser(
    tool: str, verb: str, slug: str, system_slug: str | None
) -> ArgumentParser:
    """`slug`'s parser for a verb with no descriptor behind it; the system it
    hands the options is `system_slug`'s, or none when that cannot load here."""
    module = _command_module(tool, slug, verb)
    p = ArgumentParser(prog=f"tdd {tool} {verb}", description=_summary(module))
    p.tdx_system = _system_or_none(system_slug)  # type: ignore[attr-defined]
    module.add_arguments(p)
    cli.add_format_verbose(p)
    return p


def _verb_parser(tool: str, verb: str, slug: str, info):
    """(parser, system, module) for a delegated verb on a `slug` target: the
    options depend on the type, and on the stored descriptor it is bound to.
    One construction for the run and for a batch parent's check of it."""
    system = systems.get(slug)
    if info is not None:
        bind = getattr(system, "configure", None)
        if bind is not None:
            bind(info.meta)
    module = _command_module(tool, slug, verb)
    p = ArgumentParser(prog=f"tdd {tool} {verb}", description=_summary(module))
    p.tdx_system = system  # type: ignore[attr-defined]
    module.add_arguments(p)
    cli.add_format_verbose(p)
    return p, system, module
