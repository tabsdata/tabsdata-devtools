#
# Copyright 2026 Tabsdata Inc.
#

"""system / domain -- manager for external systems and the domains inside them.

    tdd system types                          # system types, toolsets, images
    tdd system list [--sys-dir DIR]           # systems in the store
    tdd system manifest [--out FILE]          # YAML manifest of the store
    tdd system info --sys NAME|list|ALL | --manifest FILE [--as json|export|unset] [--prefix P]
    tdd system create  --type TYPE [--sys NAME] [--sys-prefix P] [--ports P,..] [--sys-hostname HOST]
    tdd system create  --type ALL|t1,t2 [--sys-prefix P]         # one per type
    tdd system destroy --sys NAME|s1,s2|ALL | --manifest FILE [--force] [--dry-run]
    tdd system status  --sys NAME|list|ALL | --manifest FILE
    tdd system purge   --sys NAME|list|ALL [--external-prefix PREFIX] [--force]
    tdd system restart --sys NAME|list|ALL | --manifest FILE
    tdd system fetch-bin [--type TYPE|t1,t2|ALL]
    tdd system connect --remote-sys [user@]HOST:PATH --remote-secret-env VAR --sys NAME
                       [--ssh-port N] [--identity KEYFILE] [--force]
    tdd system upgrade [--sys-dir DIR]        # convert legacy TDX2 descriptors
    tdd system secrets --set 1p:<vault> [--as json|export|unset]
    tdd system crypto-key [--vault V] [--item I] [--field F] [--as json|export|unset]
    tdd system clean-docker [--yes]           # stop and delete every tdx2* docker container

    tdd domain list [--domain-dir DIR]
    tdd domain manifest [--out FILE]
    tdd domain upgrade [--domain-dir DIR]
    tdd domain info --domain NAME|list|ALL | --manifest FILE [--as ...]
    tdd domain create      --sys NAME [--domain NAME] [--domain-prefix P] [--force]
    tdd domain create      --sys ALL|s1,s2 [--domain-prefix P]   # one domain / system
    tdd domain destroy     --domain NAME|d1,d2|ALL [--force] [--dry-run]
    tdd domain status      --domain NAME
    tdd domain models      --domain NAME
    tdd domain create-model --domain NAME --model MODEL
    tdd domain create-data  --domain NAME --size N
    tdd domain modify-data  --domain NAME --entity NAME|ALL --sets N
                            --ops Insert|Update|Delete|Mix --seed N|AUTO

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
``--fail-fast`` stops on the first failure and ``--report FILE`` writes a JSON run
record. ``create --manifest FILE`` replays a YAML manifest in parallel and
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
in the background; their chatty detail goes to a ``/tmp/tdd-<tool>-...log``
while the console shows brief progress.
"""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from pathlib import Path
from types import ModuleType

from tabsdata_dev.common.core import proc
from tabsdata_dev.common.core import secrets as core_secrets
from tabsdata_dev.common.systems import (
    batch,
    cli,
    console,
    constants,
    crypto,
    descriptor,
    manifest,
    store,
    systems,
)
from tabsdata_dev.common.systems.cli import ArgumentParser
from tabsdata_dev.common.systems import shell
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
}
# Verbs that accept ``--latch FILE`` (the long-running ones).
LATCH_VERBS = {
    constants.V_CREATE,
    constants.V_DESTROY,
    constants.V_PURGE,
    constants.V_CREATE_MODEL,
    constants.V_CREATE_DATA,
    constants.V_MODIFY_DATA,
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
    {constants.V_CREATE_MODEL, constants.V_CREATE_DATA, constants.V_MODIFY_DATA}
)

# ======================================================================
# Command discovery / loading -- a shared catalog gated by capability flags
# ======================================================================

_SYS_CATALOG: dict[str, tuple[str, str | None]] = {
    constants.V_CREATE: ("sys_create", None),
    constants.V_DESTROY: ("sys_destroy", None),
    constants.V_STATUS: ("sys_status", None),
    constants.V_PURGE: ("sys_purge", "supports_purge"),
    constants.V_RESTART: ("sys_restart", "is_container"),
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
}

_COMMANDS_PKG = f"{systems.__name__}._common.commands"


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
    doc = (module.__doc__ or "").strip()
    return doc.splitlines()[0] if doc else ""


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


def _reroute(tool: str, verb: str, rest: list[str], needed: str) -> int | None:
    """Hand the invocation to the sibling tool of toolset `needed` when this
    tool is not it. None when this tool is the right one."""
    running = os.environ.get("_TDD_TOOL", tool)
    wanted = (
        constants.DOMAIN_TOOL_BY_TOOLSET.get(needed)
        if _is_domain_tool(tool)
        else constants.SYS_TOOL
    )
    if wanted is None or wanted == running:
        return None
    if not os.environ.get("TDD_DIR"):
        raise TdxError(
            f"this verb needs the '{needed}' toolset ({wanted}); run it through tdd so it "
            f"can be dispatched there"
        )
    console.debug(f"re-dispatching to {wanted} (toolset {needed})")
    fmt = console.renderer().fmt
    passthrough = [verb, *rest]
    if constants.OPT_FORMAT not in rest and not any(
        a.startswith(f"{constants.OPT_FORMAT}=") for a in rest
    ):
        passthrough += [constants.OPT_FORMAT, fmt]
    console.mark_final()  # the child speaks for the run
    return proc.run_tool(wanted, *passthrough).returncode


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


def _cmn_types(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_TYPES}")
    cli.add_format_verbose(p)
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


def _cmn_sys_list(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_LIST}")
    cli.add_sys_dir(p)
    cli.add_format_verbose(p)
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
        descriptor.info_render(info, fmt, name.upper() if is_batch else prefix)
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
    # `eval "$(tdd domain info --domain x --as export)"` keeps working.
    console.good(text)
    return 0


def _cmn_sys_info(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_INFO}")
    cli.add_sys(p, required=False)
    cli.add_sys_dir(p)
    _add_info_manifest(p)
    cli.add_as(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    names, is_batch = _info_targets(tool, a.sys, a.manifest, a.sys_dir)
    return _render_infos(tool, names, a.sys_dir, a.as_, a.prefix, is_batch)


def _cmn_dom_list(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_LIST}")
    cli.add_domain_dir(p)
    cli.add_format_verbose(p)
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


def _cmn_sys_upgrade(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_UPGRADE}")
    cli.add_sys_dir(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    return _upgrade_store(store.system_dir(a.sys_dir), constants.ROLE_SYSTEM)


def _cmn_dom_upgrade(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_UPGRADE}")
    cli.add_domain_dir(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    return _upgrade_store(store.domain_dir(a.domain_dir), constants.ROLE_DOMAIN)


def _cmn_dom_info(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_INFO}")
    cli.add_domain(p, required=False)
    cli.add_domain_dir(p)
    _add_info_manifest(p)
    cli.add_as(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    names, is_batch = _info_targets(tool, a.domain, a.manifest, a.domain_dir)
    return _render_infos(tool, names, a.domain_dir, a.as_, a.prefix, is_batch)


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


def _cmn_sys_manifest(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_MANIFEST}")
    cli.add_sys_dir(p)
    _add_manifest_out(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    infos = _store_infos(
        store.system_dir(a.sys_dir), constants.ROLE_SYSTEM, strict=True
    )
    return _write_manifest(tool, a.out, [manifest.system_entry(i) for i in infos])  # type: ignore[arg-type]


def _cmn_dom_manifest(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(prog=f"tdd {tool} {constants.V_MANIFEST}")
    cli.add_domain_dir(p)
    _add_manifest_out(p)
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    infos = _store_infos(
        store.domain_dir(a.domain_dir), constants.ROLE_DOMAIN, strict=True
    )
    return _write_manifest(tool, a.out, [manifest.domain_entry(i) for i in infos])  # type: ignore[arg-type]


def _cmn_secrets(tool: str, rest: list[str]) -> int:
    p = ArgumentParser(
        prog=f"tdd {tool} {constants.V_SECRETS}",
        description="fetch a provider's secrets as the systems' env vars and "
        "print them (source the export/unset form to (un)set your shell)",
    )
    p.add_argument(
        constants.OPT_SET,
        dest="ref",
        required=True,
        metavar="PROVIDER:REF",
        help="provider ref, e.g. 1p:<vault> (1Password via the `op` CLI)",
    )
    p.add_argument(
        constants.OPT_AS,
        dest="as_",
        default=core_secrets.OUT_FORMATS[0],
        choices=list(core_secrets.OUT_FORMATS),
        help=f"output shape (default: {core_secrets.OUT_FORMATS[0]})",
    )
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    found = core_secrets.with_systems_var(core_secrets.fetch(a.ref))
    console.result({"as": a.as_, "names": list(found)})
    console.good(core_secrets.render(found, a.as_))
    return 0


def _cmn_crypto_key(tool: str, rest: list[str]) -> int:
    """Fetch the personal descriptor key -- what `secrets` does, for the one
    variable everything else needs first. Deliberately never reads the store,
    so it works before the key is set."""
    from tabsdata_dev.common.systems import crypto

    p = ArgumentParser(
        prog=f"tdd {tool} {constants.V_CRYPTO_KEY}",
        description=f"fetch ${constants.ENV_CRYPTO_KEY} from 1Password and print it "
        "(source the export form to set it in your shell)",
    )
    p.add_argument(
        constants.OPT_VAULT,
        default=constants.DEFAULT_EMPLOYEE_VAULT,
        metavar="VAULT",
        help=f"1Password vault, plain or as the provider ref 1p:VAULT that "
        f"`tdd env set` speaks (default: {constants.DEFAULT_EMPLOYEE_VAULT}); no "
        "variable of the environment is consulted",
    )
    p.add_argument(
        constants.OPT_ITEM,
        default=constants.DEFAULT_CRYPTO_ITEM,
        metavar="ITEM",
        help=f"item in the vault (default: {constants.DEFAULT_CRYPTO_ITEM})",
    )
    p.add_argument(
        constants.OPT_FIELD,
        default=constants.DEFAULT_CRYPTO_FIELD,
        metavar="FIELD",
        help=f"field of the item (default: {constants.DEFAULT_CRYPTO_FIELD})",
    )
    p.add_argument(
        constants.OPT_AS,
        dest="as_",
        default=core_secrets.OUT_FORMATS[0],
        choices=list(core_secrets.OUT_FORMATS),
        help=f"output shape (default: {core_secrets.OUT_FORMATS[0]})",
    )
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    # 1p is this verb's only provider, so a ref that names it says nothing more
    # than the bare vault does -- both spellings resolve to the same vault.
    scheme, sep, rest_ = a.vault.partition(":")
    if sep and scheme == "1p" and rest_:
        a.vault = rest_
    console.debug(f"op read op://{a.vault}/{a.item}/{a.field}")
    value = core_secrets.read_field("1p", a.vault, a.item, a.field)
    if len(value) < crypto.MIN_SECRET_LEN:
        raise TdxError(
            f"{constants.ENV_CRYPTO_KEY} from op://{a.vault}/{a.item}/{a.field} is "
            f"{len(value)} characters; it must be at least {crypto.MIN_SECRET_LEN}"
        )
    found = {constants.ENV_CRYPTO_KEY: value}
    console.result(
        {"as": a.as_, "names": list(found), "vault": a.vault, "item": a.item}
    )
    console.good(core_secrets.render(found, a.as_))
    return 0


def _cmn_clean_docker(tool: str, rest: list[str]) -> int:
    """Stop and delete every docker container named `tdx2*` -- the ones the
    docker-backed systems create -- whether or not a descriptor still points at
    them. The sweep for a store that lost track of its containers, or a machine
    to be left clean. Asks first, unless --yes."""
    prefix = constants.DOCKER_CONTAINER_PREFIX
    p = ArgumentParser(
        prog=f"tdd {tool} {constants.V_CLEAN_DOCKER}",
        description=f"stop and delete every docker container whose name starts with {prefix}",
    )
    p.add_argument(
        "-y",
        constants.OPT_YES,
        action="store_true",
        help="do not ask; without it the containers are listed and a confirmation is read from the terminal (an error when there is none)",
    )
    cli.add_format_verbose(p)
    a = p.parse_args(rest)
    shell.require_docker()
    found = shell.list_containers(prefix)
    if not found:
        console.result({"prefix": prefix, "removed": [], "failed": []})
        console.good(f"no docker containers named {prefix}*")
        return 0
    width = max(len(c["name"]) for c in found)
    for c in found:
        console.out(f"  {c['name']:<{width}}  {c['state']:<10} {c['image']}")
    if not a.yes:
        if console.json_mode() or not sys.stdin.isatty():
            raise TdxError(
                f"{len(found)} container(s) named {prefix}* would be stopped and deleted "
                f"(listed above); pass {constants.OPT_YES} to proceed"
            )
        print(
            f"stop and delete these {len(found)} container(s)? [y/N] ",
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
        except Exception as exc:  # one stubborn container must not stop the sweep
            failed.append({"name": c["name"], "error": str(exc)})
            console.warn(f"  {c['name']}: {exc}")
    console.result({"prefix": prefix, "removed": removed, "failed": failed})
    if failed:
        raise TdxError(
            f"stopped and deleted {len(removed)} container(s), {len(failed)} could not be removed: "
            + ", ".join(f["name"] for f in failed)
        )
    console.good(
        f"stopped and deleted {len(removed)} docker container(s) named {prefix}*"
    )
    return 0


_COMMON = {
    constants.SYS_TOOL: {
        constants.V_TYPES: _cmn_types,
        constants.V_LIST: _cmn_sys_list,
        constants.V_INFO: _cmn_sys_info,
        constants.V_MANIFEST: _cmn_sys_manifest,
        constants.V_UPGRADE: _cmn_sys_upgrade,
        constants.V_SECRETS: _cmn_secrets,
        constants.V_CRYPTO_KEY: _cmn_crypto_key,
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

_MANIFEST_KEYS = {"name", "type", "sys", "model", "size"}


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
        steps.append(
            [
                constants.V_CREATE_DATA,
                constants.OPT_DOMAIN,
                name,
                constants.OPT_SIZE,
                str(entry["size"]),
                *d,
                *f,
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
    return batch.run(tool, verb, new_rest)


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
        return batch.run(tool, verb, rest)
    return None


# ======================================================================
# Dispatch
# ======================================================================


def _add_store_dir(tool: str, p: ArgumentParser) -> str:
    if not _is_domain_tool(tool):
        cli.add_sys_dir(p)
        return "sys_dir"
    cli.add_domain_dir(p)
    return "domain_dir"


def top_help(tool: str) -> tuple[str, dict]:
    """The tool's help: text for view, and the same as fields for json."""
    family = _family(tool)
    common = _COMMON[family]
    delegated = _discover(tool)
    verbs = list(common) + [v for v in delegated if v not in common]
    summaries = {
        constants.V_TYPES: "list system types, their toolsets and docker images",
        constants.V_LIST: "list the descriptors in the store",
        constants.V_INFO: "print a descriptor (--as json|export|unset)",
        constants.V_MANIFEST: "dump a YAML manifest of the store (--out FILE)",
        constants.V_UPGRADE: "convert legacy TDX2 descriptors in the store to TDX3",
        constants.V_SECRETS: "fetch a provider's secrets as env vars (--set 1p:VAULT)",
        constants.V_CRYPTO_KEY: f"fetch ${constants.ENV_CRYPTO_KEY} from 1Password (--as export to source it)",
        constants.V_CLEAN_DOCKER: f"stop and delete every {constants.DOCKER_CONTAINER_PREFIX}* docker container (--yes/-y to skip the prompt)",
    }
    summaries.update(delegated)
    lines = [
        f"usage: tdd {tool} <command> [options]   (tdd {tool} <command> -h for the options)",
        "",
        "commands:",
        *(f"  {v:14} {summaries.get(v, '')}" for v in verbs),
        "",
        "every command: --format json|view, --verbose/-v, --help/-h",
        "",
        "environment:",
        *(
            f"  {ev.name:24} {ev.help} [default: {ev.default}]"
            for ev in constants.ENV_VARS
        ),
        "",
        f"store: {store.system_dir()} and {store.domain_dir()} (--sys-dir / --domain-dir override)",
    ]
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
        typed_create = verb == constants.V_CREATE and family == constants.SYS_TOOL
        named_type = cli.peek(rest, constants.OPT_TYPE) if typed_create else None
        help_slug = named_type or _default_slug(tool, verb)
        module = _command_module(tool, help_slug, verb)
        p = ArgumentParser(prog=f"tdd {tool} {verb}", description=_summary(module))
        p.tdx_system = _system_or_none(
            None if typed_create and not named_type else help_slug
        )  # type: ignore[attr-defined]
        module.add_arguments(p)
        cli.add_format_verbose(p)
        p.parse_args(rest)  # prints help and exits
        return 0
    batched = _maybe_batch(tool, verb, rest)
    if batched is not None:
        return batched
    slug, name, info, path, store_dir = _resolve(tool, verb, rest)
    _require_verb(tool, slug, verb)
    rerouted = _reroute(tool, verb, rest, _needed_toolset(tool, verb, slug, info))
    if rerouted is not None:
        return rerouted
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
    args = p.parse_args(rest)
    ctx = cli.Context(family, verb, slug, system, args, name, info, path, store_dir)
    return module.run(ctx) or 0
