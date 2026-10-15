#
# Copyright 2026 Tabsdata Inc.
#
"""The project phase and the run: project -> groups -> collections (fanned out)
-> functions (SERIAL: registration order matters) ; triggers fired in batches
gated by ``detached``; the transaction monitor; the instance/project pointer
verbs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import time
from datetime import datetime, timezone

from tabsdata_dev.common.core import proc

from . import conn, ids, lanes, pointers, shell, state, suites
from .models import Monitor, Sentinel, build_instance
from .reporter import fs_token, rep, reporting, say

BUILTIN_GROUPS = {"sources", "destinations", "default"}
# Transaction statuses that mean a run FAILED. tabsdata's SDK is not importable
# from this toolset (it lives in the user's venv), so the known failed labels
# and codes are spelled out here.
FAILED_TRX = {"Stalled", "Unexpected"}
_TRX_CODES = {"L": "Stalled", "U": "Unexpected"}


def trx_status(s: str) -> str:
    return _TRX_CODES.get(s, s)


# ------------------------------------------------------------ instances ----
def cmd_list_suites(args) -> tuple[str, dict]:
    override = getattr(args, "suites_dir", None)
    root = suites.suites_dir(override)
    rows = suites.list_suites(root)
    where = "built-in" if not override else str(root)
    if not rows:
        return f"no suites under {root}", {"root": str(root), "suites": []}
    width = max(len(r["suite"]) for r in rows)
    lines = [
        f"  {r['suite']:<{width}}  domains={r['domains']:<3} collections={r['collections']:<3} "
        f"functions={r['functions']:<3} triggers={r['triggers']}"
        + (
            "  (single object: no longer read, convert it to a list of stages)"
            if r["old_form"]
            else ""
        )
        for r in rows
    ]
    text = (
        f"{len(rows)} suite(s), {where} ({root})\n"
        + "\n".join(lines)
        + "\n  --suite <type>/<name> = one descriptor; --suite <type> = every *.json in it, "
        "one instance/project per file"
    )
    return text, {
        "root": str(root),
        "builtin": not override,
        "suites": rows,
        "dirs": suites.suite_dirs(root),
    }


def store_rows() -> list[dict]:
    """Every system in the tdd store (name, type, exclusive), asked of `tdd system list`
    (the descriptors are encrypted; only that tool reads them). Separate so a
    test can stand in for the store."""
    r = subprocess.run(
        proc.tool_argv("system", "list", "--format", "json"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=shell.domain_env(),
    )
    events = []
    for line in (r.stdout or "").splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    if r.returncode != 0:
        why = next(
            (e.get("message") for e in reversed(events) if e.get("event") == "error"),
            (r.stderr or "").strip() or f"exit {r.returncode}",
        )
        state.die(f"tdd system list failed: {why}")
    ok = next((e for e in reversed(events) if e.get("event") == "ok"), {})
    return list(ok.get("systems", []))


def _store_systems() -> dict[str, str]:
    return {row["name"]: row["system"] for row in store_rows()}


def exclusive_systems() -> set[str]:
    return {row["name"] for row in store_rows() if row.get("exclusive")}


def cmd_list_systems(args) -> tuple[str, dict]:
    """The systems a suite's domains need, each checked against the tdd system
    store: name, type, present or MISSING, and which lane(s) need it. One
    missing system fails the command -- this is the pre-flight a run wants
    before spending minutes on an instance whose lanes cannot provision."""
    root = suites.suites_dir(getattr(args, "suites_dir", None))
    path, files = suites.resolve(args.suite, root)
    needed: dict[str, list[str]] = {}
    for f in files if files is not None else [path]:
        inst = build_instance(suites.token(f), f)
        for d in inst.domains:
            lanes_ = needed.setdefault(d.system, [])
            if suites.label(f) not in lanes_:
                lanes_.append(suites.label(f))
    store = _store_systems()
    rows = [
        {
            "name": name,
            "type": store.get(name),
            "present": name in store,
            "suites": lanes_,
        }
        for name, lanes_ in sorted(needed.items())
    ]
    missing = [r["name"] for r in rows if not r["present"]]
    width = max([len(r["name"]) for r in rows] + [6])
    lines = [
        f"  {r['name']:<{width}}  {(r['type'] or '-'):<12}"
        f"{'ok     ' if r['present'] else 'MISSING'}  {', '.join(r['suites'])}"
        for r in rows
    ]
    head = f"{len(rows)} system(s) required by {args.suite} ({len(missing)} missing)"
    fields = {"suite": args.suite, "systems": rows, "missing": missing}
    if missing:
        for line in [head, *lines]:
            state.run.out.info(line, xp="note")
        state.die(
            f"{len(missing)} required system(s) not in the tdd store: {', '.join(missing)}"
            " -- create them (tdd system create --type <type> --sys <name>) or load their"
            " descriptors, then retry"
        )
    return "\n".join([head, *lines]), fields


def cmd_export_suites(args) -> tuple[str, dict]:
    out = suites.export(pathlib.Path(args.dir), bool(getattr(args, "force", False)))
    return (
        f"exported the built-in suites to {out['dir']}: suites/ ({out['suites']} files), "
        f"connections/ ({out['connections']} files); use them with --suites-dir {out['dir']}/suites",
        out,
    )


def cmd_list_instances(args) -> tuple[str, dict]:
    ptrs = pointers.members("i-")
    if not ptrs:
        return f"no instances under {pointers.store()}", {
            "store": str(pointers.store()),
            "instances": [],
        }
    owner = pointers.member_of(ptrs)
    rows, lines = [], []
    for name in sorted(ptrs):
        doc = ptrs[name]
        if isinstance(doc, dict) and doc.get("group") is not None:
            detail = f"group: {len(doc.get('group') or [])} lane(s)  suite={doc.get('suite', '?')}"
        elif isinstance(doc, dict) and doc.get("file"):
            detail = f"suite={doc['file']}" + (
                f"  (lane of {owner[name]})" if name in owner else ""
            )
        else:
            detail = "malformed pointer"
        rows.append({"name": name, **(doc or {}), "group_of": owner.get(name)})
        lines.append(f"  {name:46} {detail}")
    return f"{len(rows)} instance(s) under {pointers.store()}\n" + "\n".join(lines), {
        "store": str(pointers.store()),
        "instances": rows,
    }


def cmd_list_projects(args) -> tuple[str, dict]:
    ptrs = pointers.members("p-")
    if not ptrs:
        return f"no projects under {pointers.store()}", {
            "store": str(pointers.store()),
            "projects": [],
        }
    owner = pointers.member_of(ptrs)
    rows, lines = [], []
    for name in sorted(ptrs):
        doc = ptrs[name]
        if isinstance(doc, dict) and doc.get("group") is not None:
            detail = f"group: {len(doc.get('group') or [])} member(s)"
        elif isinstance(doc, dict) and doc.get("instance"):
            detail = f"suite_run={doc['instance']}" + (
                f"  (member of {owner[name]})" if name in owner else ""
            )
        else:
            detail = "malformed pointer"
        rows.append({"name": name, **(doc or {}), "group_of": owner.get(name)})
        lines.append(f"  {name:46} {detail}")
    return f"{len(rows)} project(s) under {pointers.store()}\n" + "\n".join(lines), {
        "store": str(pointers.store()),
        "projects": rows,
    }


def _reused(name: str, path: pathlib.Path, group: bool) -> bool:
    """Whether suite run `name` exists already -- then it is reused, its XP_ID
    with it: how a failed run is finished, a phase at a time. Of another suite
    it is refused, not repointed."""
    doc = pointers.doc_of(pointers.instance_file(name))
    if not doc:
        return False
    was = doc.get("suite") if group else doc.get("file")
    if not was or pathlib.Path(was) != path:
        state.die(
            f"suite run '{name}' exists for {was or 'something else'}, not {path} -- "
            f"`destroy-instance --suite-run {name}` first, or name another"
        )
    if not doc.get("xp_id"):
        state.die(
            f"suite run '{name}' holds no XP_ID (an older xp wrote it): "
            f"`destroy-instance --suite-run {name}`, then create it again"
        )
    return True


def create_suite_run(
    suite: str, suites_dir: str | None, name: str | None
) -> tuple[str, pathlib.Path, list[pathlib.Path] | None]:
    """The suite run `name` -- default: a new XP_ID -- for `suite`, made or, if
    it exists, reused. A suite dir is a group: an ID of its own, and one member
    per lane (``<name>_<lane>``), each a run with its own ID -- `ids.new` keeps
    them a second apart. ``(name, path, lanes)``."""
    path, files = suites.resolve(suite, suites.suites_dir(suites_dir))
    if name and _reused(name, path, files is not None):
        say(f"suite run '{name}' exists: reusing it, and its XP_ID")
        return name, path, files
    run_ids = ids.new()
    name = name or run_ids[0]
    if files is None:
        inst = build_instance(name, path, *run_ids)  # validates the descriptor
        pointers.write_instance(name, path, run_ids)
        return name, path, None
    say(f"create-instance group '{name}' from suite dir {path} ({len(files)} lanes)")
    members = []
    for definition in files:
        member = f"{name}_{definition.stem}"
        member_ids = ids.new()
        inst = build_instance(member, definition, *member_ids)
        pointers.write_instance(member, definition, member_ids)
        members.append(member)
        say(
            f"   {member:46} {member_ids[0]} d={len(inst.domains)} c={len(inst.collections)} f={len(inst.functions)} t={len(inst.triggers)}"
        )
    pointers.write_group_instance(name, members, path, run_ids)
    return name, path, files


def cmd_create_instance(args) -> tuple[str, dict]:
    name, path, files = create_suite_run(
        args.suite, getattr(args, "suites_dir", None), getattr(args, "suite_run", None)
    )
    xp_id, short_id = pointers.ids_of(name) or ("", "")
    pointer = str(pointers.instance_file(name))
    if files is not None:
        lanes_ = pointers.instance_group(name) or []
        return (
            f"suite run '{name}' ({xp_id}, short {short_id}): group pointer {pointer} ({len(lanes_)} lanes)",
            {
                "suite_run": name,
                "xp_id": xp_id,
                "xp_short_id": short_id,
                "suite": str(path),
                "lanes": lanes_,
                "pointer": pointer,
            },
        )
    inst = pointers.load_instance(name)
    return (
        f"suite run '{name}' ({xp_id}, short {short_id}) of suite {suites.label(path)} at {pointer}: domains={len(inst.domains)} collections={len(inst.collections)} functions={len(inst.functions)} triggers={len(inst.triggers)}",
        {
            "suite_run": name,
            "xp_id": xp_id,
            "xp_short_id": short_id,
            "suite": str(path),
            "pointer": pointer,
            "domains": len(inst.domains),
            "collections": len(inst.collections),
            "functions": len(inst.functions),
            "triggers": len(inst.triggers),
        },
    )


def cmd_destroy_instance(args) -> tuple[str, dict]:
    """Remove the local suite run pointer(s). Does NOT touch domains or projects."""
    members = pointers.instance_group(args.suite_run)
    removed = []
    if members is not None:
        for m in members:
            pointers.instance_file(m).unlink(missing_ok=True)
            removed.append(m)
            say(f"   removed member {pointers.instance_file(m)}")
        pointers.instance_file(args.suite_run).unlink(missing_ok=True)
        return (
            f"removed group pointer {pointers.instance_file(args.suite_run)} ({len(members)} lanes)",
            {"suite_run": args.suite_run, "removed": removed + [args.suite_run]},
        )
    path = pointers.instance_file(args.suite_run)
    if path.exists():
        path.unlink()
        return f"removed {path}", {
            "suite_run": args.suite_run,
            "removed": [args.suite_run],
        }
    return f"suite run '{args.suite_run}' absent ({path})", {
        "suite_run": args.suite_run,
        "removed": [],
    }


# -------------------------------------------------------------- project ----
def default_project(suite_run: str) -> str:
    """``<XP_ID>_<suite path>``: the project a suite run gets unless
    ``--project`` names one -- a group's too, its lanes ``<that>_<lane>``."""
    doc = pointers.doc_of(pointers.instance_file(suite_run))
    ref = doc.get("file") or doc.get("suite")
    xp_id = (pointers.ids_of(suite_run) or ("",))[0]
    if not ref or not xp_id:
        pointers.load_instance(suite_run)  # says why
    return f"{xp_id}_{suites.token(pathlib.Path(ref))}"


def claim_project(project: str, suite_run: str, force: bool) -> None:
    """`project` for `suite_run`, before anything is made in it. One this suite
    run already holds is continued -- a rerun finishes what a failed one left.
    One on the server that is not this run's is someone else's: refused, unless
    ``--force``, which deletes it so it is made again from nothing."""
    if state.run.dry_run:
        return
    if pointers.doc_of(pointers.project_file(project)).get("instance") == suite_run:
        return
    if not shell.project_exists(project):
        return
    if not force:
        state.die(
            f"project '{project}' exists and is not suite run '{suite_run}''s -- "
            "--force deletes it and creates it again"
        )
    rep().note(f"--force: deleting project '{project}' to create it again")
    delete_project(project, force=True)


def cmd_create_project(args) -> None:
    if not getattr(args, "project", None):
        args.project = default_project(args.suite_run)
    with reporting(
        args,
        "create-project",
        args.project,
        suite=pointers.suite_of_instance(args.suite_run),
    ):
        members = pointers.instance_group(args.suite_run)
        if members is not None:
            pairs = [
                (m, f"{args.project}_{lanes.lane_of(args.suite_run, m)}")
                for m in members
            ]
            lanes.dispatch(
                f"create-project group '{args.project}'",
                [
                    (
                        mp,
                        lanes.child_argv(
                            "create-project",
                            "--suite-run",
                            mi,
                            "--project",
                            mp,
                            "--secret-env",
                            state.run.secret_env,
                            *(["--force"] if getattr(args, "force", False) else []),
                            *shell.profile_flag(),
                            *shell.dry_flag(),
                        ),
                    )
                    for mi, mp in pairs
                ],
                phase="project",
                base=args.project,
            )
            pointers.write_group_project(args.project, [mp for _, mp in pairs])
            rep().note(
                f"group project pointer {pointers.project_file(args.project)} written"
            )
            return
        shell.require_login()
        inst = pointers.load_instance(args.suite_run)
        claim_project(args.project, args.suite_run, getattr(args, "force", False))
        pointers.write_project(args.project, args.suite_run)
        ensure_project(inst, args.project)
        create_collections(inst, args.project, inst.collections)
        register_functions(inst, args.project, inst.functions)
        rep().note(f"project pointer {pointers.project_file(args.project)} written")


# ------------------------------------------------------------- stages ----
# One per kind of suite stage, over the entries that stage holds: the phase
# verbs call them over every entry of their kind, run-suite over each stage in
# order.
def ensure_project(inst, project: str) -> None:
    rep().plan(1)
    with rep().step("create-project", project) as step:
        if shell.project_exists(project):
            step["note"] = "exists"
        else:
            shell.tdk(
                [
                    "project",
                    "create",
                    "--name",
                    project,
                    "--description",
                    f"{inst.type} suite ({inst.name})",
                ],
                want_json=False,
            )


def create_collections(inst, project: str, collections: list) -> None:
    # Custom collection groups must exist before a collection can be assigned.
    groups = sorted({c.group for c in collections if c.group not in BUILTIN_GROUPS})
    rep().plan(len(groups) + len(collections))

    def _create_group(g):
        with rep().step("create-group", f"{project}/{g}") as step:
            r = shell.tdk(
                ["group", "create", "--proj", project, "--name", g],
                want_json=False,
                check=False,
            )
            if r.returncode != 0:
                step["note"] = "exists"

    have = shell.collection_names(project)

    def _create_collection(c):
        with rep().step("create-collection", f"{project}/{c.name}") as step:
            if c.name in have:
                step["note"] = "exists"
                return
            cmd = [
                "collection",
                "create",
                "--proj",
                project,
                "--name",
                c.name,
                "--group",
                c.group,
            ]
            conn_yaml = None
            # Compute-only (transformer) collections have no template: created
            # connection-less (the group must not be sources/destinations).
            if c.connection_template:
                template = inst.conn_template_path(c.connection_template)
                if not template.exists():
                    state.die(f"connection template not found: {template}")
                cmd += ["--conn-file", "-"]
                # Under --dry-run skip secret resolution entirely (it would read
                # the domain descriptors and could print resolved values).
                if not state.run.dry_run:
                    conn_yaml = conn.prepare_conn(
                        template, shell.collection_descriptor(inst, c)
                    )
            shell.tdk(cmd, want_json=False, stdin_text=conn_yaml)
            step["note"] = c.type

    lanes.parallel(groups, _create_group)
    lanes.parallel(collections, _create_collection)


def fn_name(f) -> str:
    """The FUNCTION a registration names: the ::symbol when the path selects
    one, else the file (tdx-xp showed the file stem for both)."""
    return (
        f.functionpath.split("::", 1)[1]
        if "::" in f.functionpath
        else pathlib.Path(conn.fn_file(f.functionpath)).stem
    )


def register_functions(inst, project: str, functions: list) -> None:
    """SERIAL: registration order is what the dependency graph is built from.
    ``enabled: false`` registers disabled -- a stream publisher then does not
    start until it is enabled."""
    rep().plan(len(functions))
    by_name = {c.name: c for c in inst.collections}
    bags: dict[str, dict] = {}

    def _values(coll: str) -> dict:
        if coll not in bags:
            c = by_name.get(coll)
            if c is None:
                state.die(f"function names unknown collection {coll!r}")
            bags[coll] = {
                **os.environ,
                **{
                    k: str(v)
                    for k, v in shell.collection_descriptor(inst, c).items()
                    if v is not None
                },
            }
        return bags[coll]

    for f in functions:
        fn = fn_name(f)
        with rep().step("register-fn", f"{project}/{f.collection}/{fn}") as step:
            if f.local_pkg:
                state.die(
                    f"function {f.collection}:{fn} sets local_pkg, but tdk's `fn register --local-pkg` is disabled -- bundle via dir_to_bundle instead"
                )
            path, bundle = conn.render_function(
                inst, f, lambda coll=f.collection: _values(coll)
            )
            cmd = [
                "fn",
                "register",
                "--update",
                "--proj",
                project,
                "--coll",
                f.collection,
                "--path",
                path,
            ]
            if bundle:
                cmd += ["--dir-to-bundle", bundle]
            if not f.enabled:
                cmd.append("--disabled")
                step["note"] = "disabled"
            shell.tdk(cmd, want_json=False)


def fire_triggers(inst, project: str, triggers: list) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    rep().plan(len(triggers))

    def _trigger(t):
        with rep().step("trigger-fn", f"{project}/{t.collection}/{t.function}") as step:
            plan = plan_name(ts, project, t.function)
            cmd = [
                "fn",
                "trigger",
                "--proj",
                project,
                "--coll",
                t.collection,
                "--name",
                t.function,
                "--plan-name",
                plan,
            ]
            if t.detached:
                cmd.append("--detach")
            shell.tdk(cmd, want_json=False)
            step["note"] = f"plan={plan}" + ("" if t.detached else ", gated")

    for batch in trigger_batches(triggers):
        lanes.parallel(batch, _trigger)


def watch(project: str, monitor: Monitor) -> None:
    rep().plan(1)
    with rep().step("monitor", project) as step:
        step["note"] = str(monitor.time_out)
        monitor_trx(project, monitor)


def cmd_destroy_project(args) -> None:
    force = bool(getattr(args, "force", False))
    with reporting(
        args,
        "destroy-project",
        args.project,
        suite=pointers.suite_of_project(args.project),
    ):
        members = pointers.project_group(args.project)
        if members is not None:
            lanes.dispatch(
                f"destroy-project group '{args.project}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "destroy-project",
                            "--project",
                            m,
                            *(["--force"] if force else []),
                            *shell.profile_flag(),
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
            )
            pointers.project_file(args.project).unlink(missing_ok=True)
            rep().note(f"group pointer {pointers.project_file(args.project)} removed")
            return
        shell.require_login()
        delete_project(args.project, force)


def delete_project(project: str, force: bool) -> None:
    """Delete `project` and its pointer: its collections first (cascading their
    functions and tables), in parallel, then the project."""
    if not state.run.dry_run and not shell.project_exists(project):
        rep().plan(1)
        with rep().step("destroy-project", project) as step:
            step["note"] = "absent"
        pointers.project_file(project).unlink(missing_ok=True)
        return
    # A project must be empty before it can be deleted.
    if state.run.dry_run:
        colls = sorted(
            c.name
            for c in pointers.load_instance(pointers.load_project(project)).collections
        )
    else:
        colls = sorted(shell.collection_names(project))
    rep().plan(len(colls) + 1)

    def _delete_collection(name):
        with rep().step("delete-collection", f"{project}/{name}") as step:
            r = shell.tdk(
                [
                    "collection",
                    "delete",
                    "--proj",
                    project,
                    "--name",
                    name,
                    "--confirm",
                    "delete",
                ],
                want_json=False,
                check=not force,
            )
            if r.returncode != 0:
                step["note"] = (
                    f"delete failed, continuing (--force): {shell.last_err(r)}"
                )

    lanes.parallel(colls, _delete_collection)
    with rep().step("delete-project", project) as step:
        r = shell.tdk(
            ["project", "delete", "--name", project, "--confirm", "delete"],
            want_json=False,
            check=not force,
        )
        if r.returncode != 0:
            step["note"] = f"delete failed, continuing (--force): {shell.last_err(r)}"
    pointers.project_file(project).unlink(missing_ok=True)
    rep().note(f"pointer {pointers.project_file(project)} removed")


# -------------------------------------------------------------- monitor ----
#: How long the monitor may keep failing before the run is given up on, how
#: long to wait between attempts, and how long a watch must have lasted to
#: prove the server was reachable (which restarts the outage clock).
MONITOR_OUTAGE_GRACE = 120.0
MONITOR_RETRY_PAUSE = 5.0
MONITOR_HEALTHY_WATCH = 30.0


def _watch(
    argv: list[str], project: str, left: float
) -> subprocess.CompletedProcess | None:
    """One watch, for at most `left` seconds; None when they ran out (the
    watch is killed)."""
    try:
        if state.run.out.fmt == "json":
            return shell.run_cmd(argv, check=False, timeout=left)
        rep().note(f"monitor '{project}' (Ctrl-C to stop watching)")
        shell.flush_stdout()
        return subprocess.run(argv, timeout=left)
    except subprocess.TimeoutExpired:
        return None


def monitor_trx(project: str, monitor: Monitor) -> None:
    """Wait for every transaction in ``project`` to finish, then FAIL if any
    ended in a failed state. In view the monitor streams to the terminal (its
    live table is the point); in json it is captured into run.log instead.

    A monitor that exits non-zero is started again: it only reads, and the
    usual cause is the connection -- a cluster run reaches the apiserver
    through a port-forward that drops and is relaunched in seconds, and one
    drop used to fail every lane watching at that moment while their
    transactions ran on. Only a monitor that keeps failing for
    ``MONITOR_OUTAGE_GRACE`` seconds fails the run; one that fails at once for
    another reason (a lost login) never lasts long enough to restart the clock,
    so it too ends within the grace period.

    The whole watch -- every attempt, every pause -- ends at the monitor's
    ``time_out``: transactions still running then fail the run."""
    argv = shell.tdk_argv("trx", "list", "--proj", project, "--monitor")
    if state.run.dry_run:
        shell.dry_echo(argv)
        return
    deadline = time.monotonic() + monitor.seconds
    down_since = None
    while True:
        started = time.monotonic()
        left = deadline - started
        r = _watch(argv, project, left) if left > 0 else None
        if r is None:
            state.die(
                f"project '{project}' still has transactions running after the "
                f"monitor's time_out ({monitor.time_out})"
            )
        if r.returncode == 0:
            break
        now = time.monotonic()
        if down_since is None or now - started >= MONITOR_HEALTHY_WATCH:
            down_since = now
        why = shell.last_err(r) if r.stderr else "see the output above"
        if now - down_since >= MONITOR_OUTAGE_GRACE:
            state.die(
                f"transaction monitor exited with {r.returncode} for project '{project}' "
                f"and kept failing for {MONITOR_OUTAGE_GRACE:g}s ({why}) -- refusing to "
                "report success over an unwatched run"
            )
        rep().note(
            f"monitor '{project}' exited with {r.returncode} ({why}); watching again in "
            f"{MONITOR_RETRY_PAUSE:g}s"
        )
        time.sleep(max(0.0, min(MONITOR_RETRY_PAUSE, deadline - time.monotonic())))
    trx = shell.tdk(["trx", "list", "--proj", project], check=False) or []
    failed = [t for t in trx if trx_status(str(t.get("status", ""))) in FAILED_TRX]
    if failed:
        detail = "\n".join(
            f"   {trx_status(str(t.get('status', ''))):10} {t.get('collection', '?'):26} (tx {t.get('id', '?')})"
            for t in failed
        )
        rep().log(f"failed transactions in {project}", detail)
        evidence = collect_worker_logs(failed)
        if evidence:
            rep().error(
                f"worker logs of the failed transactions in {project}", evidence
            )
            detail += "\n   worker logs:\n" + evidence
        state.die(
            f"project '{project}' has {len(failed)} failed transaction(s):\n{detail}"
        )


# ------------------------------------------------------------- sentinel ----
#: How long a sentinel waits between looks at its table's versions.
SENTINEL_POLL = 5.0
#: The column `tdd domain sentinel-data` writes the key into; a table carrying
#: the sentinel entity downstream keeps the name.
SENTINEL_KEY_COLUMN = "sentinel_key"


def wait_sentinels(project: str, sentinels: list[Sentinel]) -> None:
    """A sentinel stage: each entry in turn, one step each. Their clocks start
    when each is reached, but a key that arrived meanwhile is found on the
    first look -- every version is read -- so the stage takes as long as its
    slowest sentinel, not the sum."""
    rep().plan(len(sentinels))
    for s in sentinels:
        with rep().step("sentinel", f"{project}/{s.collection}/{s.table}") as step:
            step["note"] = s.wait_for_key
            _wait_sentinel(project, s)


def _wait_sentinel(project: str, s: Sentinel) -> None:
    """Poll the table's committed versions until one holds the key. A version
    is final once committed, so each is read once; one that cannot be read yet
    (the table half made, a hiccup) is tried again on the next look, and the
    time-out says how many could not be, and why.

    The key column is looked up in the table's schema rather than assumed:
    a database that upper-cases unquoted names (DB2) streams the sentinel
    entity as ``SENTINEL_KEY``, and tdk's SQL matches a column's case. It is
    then quoted, as it is spelled."""
    where = ["--proj", project, "--coll", s.collection, "--name", s.table]
    key = s.wait_for_key.replace("'", "''")
    versions_args = ["table", "versions", *where, "--max-result", "0"]
    if state.run.dry_run:
        shell.dry_echo(shell.tdk_argv(*versions_args, "--format", "json"))
        shell.dry_text(
            f"# sentinel: every {SENTINEL_POLL:g}s, each new version of {s.table} "
            f"until {s.wait_for_key!r} is in one, at most {s.time_out}"
        )
        return
    deadline = time.monotonic() + s.seconds
    read: set[str] = set()
    unreadable: dict[str, str] = {}  # version -> why, until it is read
    column: str | None = None
    while True:
        for version in shell.tdk(versions_args, check=False) or []:
            vid = str(version.get("id") or "")
            if not vid or vid in read:
                continue
            if column is None:
                schema, why = shell.tdk_read(
                    ["table", "schema", *where, "--version", vid]
                )
                if schema is None:
                    unreadable[vid] = why
                    continue
                column = _key_column(s, schema)
                if column is None:
                    # No columns at all: a flush that carried nothing for this
                    # table (a stream from its tail publishes one before the
                    # first sentinel row). It holds no key; the next may.
                    read.add(vid)
                    unreadable.pop(vid, None)
                    continue
            sql = f'SELECT "{column}" FROM {s.table} WHERE "{column}" = \'{key}\''
            rows, why = shell.tdk_read(
                ["table", "data", *where, "--version", vid, "--sql", sql, "--len", "1"]
            )
            if rows is None:
                unreadable[vid] = why
                continue
            read.add(vid)
            unreadable.pop(vid, None)
            if rows:
                rep().log(
                    f"sentinel {s.wait_for_key!r} found in {s.table} version {vid}"
                )
                return
        left = deadline - time.monotonic()
        if left <= 0:
            unread = ""
            if unreadable:
                last = next(reversed(unreadable.values())) or "no error output"
                unread = f"; {len(unreadable)} could not be read: {last}"
            state.die(
                f"sentinel {s.wait_for_key!r} not in any version of "
                f"{s.collection}/{s.table} after {s.time_out} "
                f"({len(read)} version(s) read{unread})"
            )
        time.sleep(min(SENTINEL_POLL, left))


def _key_column(s: Sentinel, schema) -> str | None:
    """The table's own spelling of the sentinel key column, or None for a
    version with no columns at all -- an empty flush, which says nothing about
    the table yet. Columns without the key are fatal at once: a table without
    it can never hold the key, and waiting out the time-out would only hide
    that."""
    names = [str(c.get("name", "")) for c in schema or [] if isinstance(c, dict)]
    if not names:
        return None
    found = next((n for n in names if n.lower() == SENTINEL_KEY_COLUMN), None)
    if found is None:
        state.die(
            f"sentinel {s.wait_for_key!r}: {s.collection}/{s.table} has no "
            f"{SENTINEL_KEY_COLUMN} column in any case (columns: {', '.join(names)})"
        )
    return str(found)


def collect_worker_logs(failed: list) -> str:
    """Save every worker log of each failed transaction under
    ``<scratch>/trx-logs/<trx>/<worker>.log`` and return one line per file.

    Done here, at the moment of failure, because it is the last moment the
    logs exist: a one-shot or smoke run tears the instance down next, and with
    it every worker. Through `worker list --trx` + `worker logs --worker`, not
    `trx logs --trx`, which asks the user to pick when several workers ran.
    Best effort: a fetch that fails is named in the result, never raised -- the
    failed transactions are the error, not the evidence."""
    lines: list[str] = []
    for t in failed:
        trx = str(t.get("id") or "")
        if not trx:
            continue
        workers = shell.tdk(["worker", "list", "--trx", trx], check=False)
        if not workers:
            lines.append(f"   {trx}: no workers listed")
            continue
        dest = rep().scratch / "trx-logs" / fs_token(trx)
        dest.mkdir(parents=True, exist_ok=True)
        for w in workers:
            wid = str(w.get("id") or "")
            if not wid:
                continue
            path = dest / f"{fs_token(wid)}.log"
            r = shell.tdk(
                ["worker", "logs", "--worker", wid, "--file", str(path)],
                want_json=False,
                check=False,
            )
            status = str(w.get("status", "?"))
            if r.returncode == 0 and path.exists():
                lines.append(f"   {trx} {status:10} {path}")
            else:
                lines.append(f"   {trx} {status:10} {wid}: {shell.last_err(r)}")
    return "\n".join(lines)


# ------------------------------------------------------------------ run ----
def trigger_batches(triggers: list) -> list[list]:
    """Batches that may fire CONCURRENTLY: a run of detached triggers is one
    batch; an attached one is a GATE, fired alone, and what follows waits."""
    batches: list[list] = []
    for t in triggers:
        if t.detached and batches and batches[-1][-1].detached:
            batches[-1].append(t)
        else:
            batches.append([t])
    return batches


#: tabsdata's ExecutionName is `max_len = 100` and it refuses the trigger
#: outright: "ExecutionName '...' longer than max_len 100".
PLAN_NAME_MAX = 100


def plan_name(ts: str, project: str, function: str) -> str:
    """The `--plan-name` for one trigger: when it ran, what ran, and where --
    inside tabsdata's 100 characters.

    Where is the project alone: it carries the run's XP_ID (or is the name
    `--project` gave, and then the timestamp still tells two runs apart). The
    suite run's name beside it says the same thing again -- a lane's project is
    `<XP_ID>_<dir>_<lane>`, its suite run `<XP_ID>_<lane>` -- and pushed every
    plan of a suite dir past the limit; a smoke run went two characters over
    that way before the IDs.

    That alone is no guarantee -- a long `--project` or function name can still
    overflow -- so the result is capped. What identifies a plan to a person sits
    at the ends (when it started, which function ran), so the middle is what
    gives way, and a digest of the full name takes its place: two plans
    truncated to the same prefix must not come out with the same name.
    """
    where = project
    name = f"{ts}_{where}_{function}"
    if len(name) <= PLAN_NAME_MAX:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    room = PLAN_NAME_MAX - len(ts) - len(function) - len(digest) - 3
    if room < 1:
        # the ends alone do not fit; the timestamp and the digest still name it
        return f"{ts}_{digest}"[:PLAN_NAME_MAX]
    return f"{ts}_{where[:room]}_{digest}_{function}"


def monitor_of(args) -> Monitor | None:
    """The monitor `--monitor --time-out T` asks for, None without --monitor;
    a watch is never without an end."""
    if not getattr(args, "monitor", True):
        return None
    if not getattr(args, "time_out", None):
        state.die(
            "--time-out <VALUE><UNIT> (e.g. 30m) says how long the monitor may watch"
        )
    try:
        return Monitor(time_out=args.time_out)
    except ValueError as exc:
        state.die(f"--time-out: {exc}")


def cmd_run_triggers(args) -> None:
    monitor = monitor_of(args)
    with reporting(
        args,
        "run-triggers",
        args.project,
        suite=pointers.suite_of_project(args.project),
    ):
        members = pointers.project_group(args.project)
        if members is not None:
            watch_flags = (
                ["--monitor", "--time-out", str(monitor.time_out)] if monitor else []
            )
            lanes.dispatch(
                f"run-triggers group '{args.project}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "run-triggers",
                            "--project",
                            m,
                            *watch_flags,
                            *shell.profile_flag(),
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="run",
                base=args.project,
            )
            return
        shell.require_login()
        inst = pointers.load_instance(pointers.load_project(args.project))
        fire_triggers(inst, args.project, inst.triggers)
        if monitor:
            watch(args.project, monitor)


def cmd_monitor_project(args) -> None:
    monitor = monitor_of(args)
    shell.require_login()
    with reporting(
        args,
        "monitor-project",
        args.project,
        suite=pointers.suite_of_project(args.project),
    ):
        members = pointers.project_group(args.project)
        if members is not None:
            lanes.dispatch(
                f"monitor-project group '{args.project}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "monitor-project",
                            "--project",
                            m,
                            "--time-out",
                            str(monitor.time_out),
                            *shell.profile_flag(),
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="monitor",
                base=args.project,
            )
            return
        watch(args.project, monitor)


def _set_enabled(args, enabled: bool) -> None:
    verb = "enable" if enabled else "disable"
    with reporting(
        args,
        f"{verb}-function",
        args.project,
        suite=pointers.suite_of_project(args.project),
    ):
        if pointers.project_group(args.project) is not None:
            state.die(
                f"project '{args.project}' is a group: name one lane's project "
                f"(`tdd xp list-projects`), whose functions are its own"
            )
        shell.require_login()
        rep().plan(1)
        path = f"{args.project}/{args.collection}/{args.function}"
        with rep().step(f"{verb}-fn", path):
            shell.tdk(
                [
                    "fn",
                    verb,
                    "--proj",
                    args.project,
                    "--coll",
                    args.collection,
                    "--name",
                    args.function,
                ],
                want_json=False,
            )


def cmd_enable_function(args) -> None:
    """Enable a registered function -- a stream publisher registered with
    ``"enabled": false`` starts here. Enabling an enabled one does nothing."""
    _set_enabled(args, True)


def cmd_disable_function(args) -> None:
    """Disable a registered function -- a stream publisher stops. Disabling a
    disabled one does nothing."""
    _set_enabled(args, False)


def ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)
