#
# Copyright 2026 Tabsdata Inc.
#

"""Run a delegated verb against many targets in parallel.

The multi-target selector is ``--type`` for a system ``create`` (one system per
type, named after it), ``--sys`` for a domain ``create`` (one domain per system,
named after it), and ``--sys`` / ``--domain`` for every other verb (each stored
system / domain). Each accepts a single name, a comma-separated list, or ``ALL``;
``--sys-prefix P`` / ``--domain-prefix P`` prepends ``P_`` to the created names.
Any list / ALL (or a lone ``--report`` / ``--fail-fast``) puts the verb in batch
mode: each target runs as its own child process through ``tdd-exe`` -- full
isolation, safe with the fork-/thread-unsafe native DB clients, and each child
lands in the toolset *it* needs -- with bounded concurrency, heaviest ``weight``
first (see :mod:`tabsdata_dev.common.core.batch`). A system ``create`` batch also
hands each child a *disjoint* pool of pre-found free ports (``--ports``) so two
parallel creates never pick the same port.
"""

from __future__ import annotations

import os
import subprocess
import sys
from collections.abc import Callable

from tabsdata_dev.common.core import batch as core_batch
from tabsdata_dev.common.core import proc
from tabsdata_dev.common.systems import (
    cli,
    console,
    constants,
    descriptor,
    store,
    systems as _systems,
)
from tabsdata_dev.common.systems.errors import TdxError

Task = core_batch.Task


def _selector(tool: str) -> str:
    return constants.OPT_DOMAIN if tool == constants.DOM_TOOL else constants.OPT_SYS


def _create_selector(tool: str) -> str:
    """The flag that drives a batch ``create``: ``--type`` (system -- one system
    per type) or ``--sys`` (domain -- one domain per system)."""
    return constants.OPT_SYS if tool == constants.DOM_TOOL else constants.OPT_TYPE


def _batch_selector(tool: str, verb: str) -> str:
    return _create_selector(tool) if verb == constants.V_CREATE else _selector(tool)


def spawn_for(tool: str) -> core_batch.Spawn:
    """How a child runs: through the dispatcher when we are under one (so a
    salesforce domain lands in its own toolset), else the tool module directly."""

    # stderr folded into stdout so the child's lines keep their order: its
    # progress goes to stderr and its ok to stdout, and two captures would
    # show the ok first.
    capture = dict(stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8")

    def spawn(argv: list[str]) -> subprocess.CompletedProcess:
        if os.environ.get("TDD_DIR"):
            return proc.run_tool(tool, *argv, **capture)
        module = f"tabsdata_dev.tool.{tool.replace('-', '_')}"
        return subprocess.run([sys.executable, "-m", module, *argv], **capture)

    return spawn


def weight_for(slug: str) -> int:
    try:
        return int(getattr(_systems.get_class(slug), "weight", 1))
    except TdxError:
        return 1


def _names(sel: str) -> list[str]:
    return [n.strip() for n in sel.split(",") if n.strip()]


def _is_all(sel: str) -> bool:
    names = _names(sel)
    return len(names) == 1 and names[0].upper() == constants.TARGET_ALL


def is_batch(tool: str, verb: str, rest: list[str]) -> bool:
    """Whether the verb targets many systems/domains (comma list or ALL) or a
    report/fail-fast was requested (so even one target runs through here)."""
    sel = cli.peek(rest, _batch_selector(tool, verb))
    if sel is None:
        return False
    if len(_names(sel)) > 1 or _is_all(sel):
        return True
    return cli.peek(rest, constants.OPT_REPORT) is not None or (
        constants.OPT_FAIL_FAST in rest
    )


def _stored(role: str) -> list[descriptor.SystemInfo | descriptor.DomainInfo]:
    store_dir = (
        store.domain_dir(None)
        if role == constants.ROLE_DOMAIN
        else store.system_dir(None)
    )
    out: list[descriptor.SystemInfo | descriptor.DomainInfo] = []
    if not store_dir.is_dir():
        return out
    for path in sorted(p for p in store_dir.iterdir() if p.is_file()):
        if not descriptor.is_descriptor(path):
            continue
        try:
            info = descriptor.load(path)
        except TdxError:
            continue
        if info.role == role:
            out.append(info)
    return out


def weight_of_stored(role: str, name: str) -> int:
    for info in _stored(role):
        if info.name == name:
            return weight_for(info.system)
    return 1


def _strip(argv: list[str], value_flags: set[str], bool_flags: set[str]) -> list[str]:
    """`argv` with the given value flags (``--flag V`` / ``--flag=V``) and bare
    bool flags removed."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        tok = argv[i]
        if tok in value_flags:
            i += 2
            continue
        if any(tok.startswith(f"{vf}=") for vf in value_flags):
            i += 1
            continue
        if tok in bool_flags:
            i += 1
            continue
        out.append(tok)
        i += 1
    return out


# Children run in view mode with their output captured; the parent renders.
_BATCH_ONLY = {constants.OPT_FAIL_FAST, constants.OPT_VERBOSE, "-v"}
_BATCH_VALUE = {constants.OPT_REPORT, constants.OPT_FORMAT}


def _expand(tool: str, verb: str, rest: list[str]) -> list[Task]:
    """The per-target Tasks for a batch verb (each carries the child's argv)."""
    tasks: list[Task] = []
    if verb == constants.V_CREATE and tool == constants.SYS_TOOL:
        prefix = cli.peek(rest, constants.OPT_SYS_PREFIX)
        sel = cli.peek(rest, constants.OPT_TYPE) or ""
        types = _systems.all_slugs() if _is_all(sel) else _names(sel)
        passthrough = _strip(
            rest,
            {constants.OPT_TYPE, constants.OPT_SYS, constants.OPT_PORTS, *_BATCH_VALUE},
            _BATCH_ONLY,
        )
        # No ports are handed down: every system type owns a fixed port slot
        # (systems._common.ports), so parallel creates cannot compete.
        for typ in types:
            argv = [
                constants.V_CREATE,
                constants.OPT_TYPE,
                typ,
                constants.OPT_SYS,
                typ,
                *passthrough,
            ]
            tasks.append(Task(cli.apply_prefix(typ, prefix), weight_for(typ), [argv]))
        return tasks
    if verb == constants.V_CREATE and tool == constants.DOM_TOOL:
        prefix = cli.peek(rest, constants.OPT_DOMAIN_PREFIX)
        sel = cli.peek(rest, constants.OPT_SYS) or ""
        sysnames = (
            [s.name for s in _stored(constants.ROLE_SYSTEM)]
            if _is_all(sel)
            else _names(sel)
        )
        passthrough = _strip(
            rest, {constants.OPT_SYS, constants.OPT_DOMAIN, *_BATCH_VALUE}, _BATCH_ONLY
        )
        for sysn in sysnames:
            argv = [
                constants.V_CREATE,
                constants.OPT_SYS,
                sysn,
                constants.OPT_DOMAIN,
                sysn,
                *passthrough,
            ]
            tasks.append(
                Task(
                    cli.apply_prefix(sysn, prefix),
                    weight_of_stored(constants.ROLE_SYSTEM, sysn),
                    [argv],
                )
            )
        return tasks
    # non-create verbs: ALL = every stored target, else the named ones
    selector = _selector(tool)
    sel = cli.peek(rest, selector) or ""
    role = (
        constants.ROLE_DOMAIN if tool == constants.DOM_TOOL else constants.ROLE_SYSTEM
    )
    passthrough = _strip(rest, {selector, *_BATCH_VALUE}, _BATCH_ONLY)
    target_names = [i.name for i in _stored(role)] if _is_all(sel) else _names(sel)
    for name in target_names:
        tasks.append(
            Task(
                name,
                weight_of_stored(role, name),
                [[verb, selector, name, *passthrough]],
            )
        )
    return tasks


def run(
    tool: str,
    verb: str,
    rest: list[str],
    *,
    final: bool = True,
    check: Callable[[list[str]], None] | None = None,
) -> int:
    """Run `verb` over the targets `rest` selects. `check`, when given, is run
    on every child's argv before any child starts and raises to refuse the
    batch (dispatch passes the parse each child would do)."""
    tasks = _expand(tool, verb, rest)
    role = "domain" if tool == constants.DOM_TOOL else "system"
    if not tasks:
        console.out(f"no {role}s matched -- nothing to do")
        return 0
    if check is not None:
        for task in tasks:
            for step in task.steps:
                check(step)
    return execute(
        tool,
        verb,
        tasks,
        report_path=cli.peek(rest, constants.OPT_REPORT),
        fail_fast=constants.OPT_FAIL_FAST in rest,
        final=final,
    )


def execute(
    tool: str,
    label: str,
    tasks: list[Task],
    *,
    report_path: str | None = None,
    fail_fast: bool = False,
    final: bool = True,
) -> int:
    """Run `tasks` through the generic runner; when it emits the summary
    (`final`) the run's ok/error is done and the caller must not add one."""
    role = "domain" if tool == constants.DOM_TOOL else "system"
    rc = core_batch.execute(
        label,
        tasks,
        spawn_for(tool),
        console.renderer(),
        role=role,
        fail_fast=fail_fast,
        report_path=report_path,
        final=final,
    )
    if final:
        console.mark_final()
    return rc
