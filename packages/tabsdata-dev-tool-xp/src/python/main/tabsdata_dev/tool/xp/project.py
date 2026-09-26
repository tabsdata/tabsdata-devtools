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

from . import conn, lanes, pointers, shell, state, suites
from .models import build_instance
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
        for r in rows
    ]
    text = (
        f"{len(rows)} suite(s), {where} ({root})\n"
        + "\n".join(lines)
        + "\n  --suite <type>/<name> = one descriptor; --suite <type> = every *.json in it, "
        "one instance/project per file"
    )
    return text, {"root": str(root), "builtin": not override, "suites": rows}


def _store_systems() -> dict[str, str]:
    """name -> type of every system in the tdd store, asked of `tdd system list`
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
    return {row["name"]: row["system"] for row in ok.get("systems", [])}


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
            detail = f"instance={doc['instance']}" + (
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


def _group_instance_members(base: str, files: list[pathlib.Path]) -> list[str]:
    """One member instance per swim lane (``<base>_<name>``); returns the names."""
    names = []
    for definition in files:
        name = f"{base}_{definition.stem}"
        inst = build_instance(name, definition)  # validates the descriptor
        pointers.write_instance(name, definition)
        names.append(name)
        say(
            f"   {name:46} d={len(inst.domains)} c={len(inst.collections)} f={len(inst.functions)} t={len(inst.triggers)}"
        )
    return names


def cmd_create_instance(args) -> tuple[str, dict]:
    path, files = suites.resolve(
        args.suite, suites.suites_dir(getattr(args, "suites_dir", None))
    )
    if files is not None:
        say(
            f"create-instance group '{args.instance}' from suite dir {path} ({len(files)} lanes)"
        )
        names = _group_instance_members(args.instance, files)
        pointers.write_group_instance(args.instance, names, path)
        return (
            f"group pointer {pointers.instance_file(args.instance)} written ({len(names)} lanes)",
            {
                "instance": args.instance,
                "suite": str(path),
                "lanes": names,
                "pointer": str(pointers.instance_file(args.instance)),
            },
        )
    inst = build_instance(args.instance, path)
    pointers.write_instance(args.instance, path)
    return (
        f"created instance '{args.instance}' (suite {suites.label(path)}) at {pointers.instance_file(args.instance)}: domains={len(inst.domains)} collections={len(inst.collections)} functions={len(inst.functions)} triggers={len(inst.triggers)}",
        {
            "instance": args.instance,
            "suite": str(path),
            "pointer": str(pointers.instance_file(args.instance)),
            "domains": len(inst.domains),
            "collections": len(inst.collections),
            "functions": len(inst.functions),
            "triggers": len(inst.triggers),
        },
    )


def cmd_destroy_instance(args) -> tuple[str, dict]:
    """Remove the local instance pointer(s). Does NOT touch domains or projects."""
    members = pointers.instance_group(args.instance)
    removed = []
    if members is not None:
        for m in members:
            pointers.instance_file(m).unlink(missing_ok=True)
            removed.append(m)
            say(f"   removed member {pointers.instance_file(m)}")
        pointers.instance_file(args.instance).unlink(missing_ok=True)
        return (
            f"removed group pointer {pointers.instance_file(args.instance)} ({len(members)} lanes)",
            {"instance": args.instance, "removed": removed + [args.instance]},
        )
    path = pointers.instance_file(args.instance)
    if path.exists():
        path.unlink()
        return f"removed {path}", {
            "instance": args.instance,
            "removed": [args.instance],
        }
    return f"instance '{args.instance}' absent ({path})", {
        "instance": args.instance,
        "removed": [],
    }


# -------------------------------------------------------------- project ----
def cmd_create_project(args) -> None:
    with reporting(
        args,
        "create-project",
        args.project,
        suite=pointers.suite_of_instance(args.instance),
    ):
        members = pointers.instance_group(args.instance)
        if members is not None:
            pairs = [
                (m, f"{args.project}_{lanes.lane_of(args.instance, m)}")
                for m in members
            ]
            lanes.dispatch(
                f"create-project group '{args.project}'",
                [
                    (
                        mp,
                        lanes.child_argv(
                            "create-project",
                            "--instance",
                            mi,
                            "--project",
                            mp,
                            "--secret-env",
                            state.run.secret_env,
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
        inst = pointers.load_instance(args.instance)
        # Custom collection groups must exist before a collection can be assigned.
        groups = sorted(
            {c.group for c in inst.collections if c.group not in BUILTIN_GROUPS}
        )
        rep().plan(1 + len(groups) + len(inst.collections) + len(inst.functions))

        with rep().step("create-project", args.project) as step:
            if shell.project_exists(args.project):
                step["note"] = "exists"
            else:
                shell.tdk(
                    [
                        "project",
                        "create",
                        "--name",
                        args.project,
                        "--description",
                        f"{inst.type} suite ({inst.name})",
                    ],
                    want_json=False,
                )

        def _create_group(g):
            with rep().step("create-group", f"{args.project}/{g}") as step:
                r = shell.tdk(
                    ["group", "create", "--proj", args.project, "--name", g],
                    want_json=False,
                    check=False,
                )
                if r.returncode != 0:
                    step["note"] = "exists"

        have = shell.collection_names(args.project)

        def _create_collection(c):
            with rep().step("create-collection", f"{args.project}/{c.name}") as step:
                if c.name in have:
                    step["note"] = "exists"
                    return
                cmd = [
                    "collection",
                    "create",
                    "--proj",
                    args.project,
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
        lanes.parallel(inst.collections, _create_collection)

        # Functions stay SERIAL: inter-function dependencies require order.
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

        for f in inst.functions:
            # The step names the FUNCTION: the ::symbol when the path selects one,
            # else the file (tdx-xp showed the file stem for both).
            fn = (
                f.functionpath.split("::", 1)[1]
                if "::" in f.functionpath
                else pathlib.Path(conn.fn_file(f.functionpath)).stem
            )
            with rep().step("register-fn", f"{args.project}/{f.collection}/{fn}"):
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
                    args.project,
                    "--coll",
                    f.collection,
                    "--path",
                    path,
                ]
                if bundle:
                    cmd += ["--dir-to-bundle", bundle]
                shell.tdk(cmd, want_json=False)

        pointers.write_project(args.project, args.instance)
        rep().note(f"project pointer {pointers.project_file(args.project)} written")


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
        if not state.run.dry_run and not shell.project_exists(args.project):
            rep().plan(1)
            with rep().step("destroy-project", args.project) as step:
                step["note"] = "absent"
            pointers.project_file(args.project).unlink(missing_ok=True)
            return
        # A project must be empty before it can be deleted: drop its collections
        # first (cascading their functions and tables), in parallel.
        if state.run.dry_run:
            colls = sorted(
                c.name
                for c in pointers.load_instance(
                    pointers.load_project(args.project)
                ).collections
            )
        else:
            colls = sorted(shell.collection_names(args.project))
        rep().plan(len(colls) + 1)

        def _delete_collection(name):
            with rep().step("delete-collection", f"{args.project}/{name}") as step:
                r = shell.tdk(
                    [
                        "collection",
                        "delete",
                        "--proj",
                        args.project,
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
        with rep().step("delete-project", args.project) as step:
            r = shell.tdk(
                ["project", "delete", "--name", args.project, "--confirm", "delete"],
                want_json=False,
                check=not force,
            )
            if r.returncode != 0:
                step["note"] = (
                    f"delete failed, continuing (--force): {shell.last_err(r)}"
                )
        pointers.project_file(args.project).unlink(missing_ok=True)
        rep().note(f"pointer {pointers.project_file(args.project)} removed")


# -------------------------------------------------------------- monitor ----
#: How long the monitor may keep failing before the run is given up on, how
#: long to wait between attempts, and how long a watch must have lasted to
#: prove the server was reachable (which restarts the outage clock).
MONITOR_OUTAGE_GRACE = 120.0
MONITOR_RETRY_PAUSE = 5.0
MONITOR_HEALTHY_WATCH = 30.0


def _watch(argv: list[str], project: str) -> subprocess.CompletedProcess:
    if state.run.out.fmt == "json":
        return shell.run_cmd(argv, check=False)
    rep().note(f"monitor '{project}' (Ctrl-C to stop watching)")
    shell.flush_stdout()
    return subprocess.run(argv)


def monitor_trx(project: str) -> None:
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
    so it too ends within the grace period."""
    argv = shell.tdk_argv("trx", "list", "--proj", project, "--monitor")
    if state.run.dry_run:
        shell.dry_echo(argv)
        return
    down_since = None
    while True:
        started = time.monotonic()
        r = _watch(argv, project)
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
        time.sleep(MONITOR_RETRY_PAUSE)
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


def plan_name(ts: str, instance: str, project: str, function: str) -> str:
    """The `--plan-name` for one trigger: when it ran, what ran, and enough of
    where to tell two runs apart -- inside tabsdata's 100 characters.

    xp names a project `<instance>_<lane>`, so naming both spends the instance
    twice; a smoke run, whose names carry a timestamp of their own, went two
    characters over the limit that way. The instance is therefore named only
    when the project does not already start with it.

    That alone is no guarantee -- a long `--project` or function name can still
    overflow -- so the result is capped. What identifies a plan to a person sits
    at the ends (when it started, which function ran), so the middle is what
    gives way, and a digest of the full name takes its place: two plans
    truncated to the same prefix must not come out with the same name.
    """
    where = project if project.startswith(instance) else f"{instance}_{project}"
    name = f"{ts}_{where}_{function}"
    if len(name) <= PLAN_NAME_MAX:
        return name
    digest = hashlib.sha256(name.encode()).hexdigest()[:8]
    room = PLAN_NAME_MAX - len(ts) - len(function) - len(digest) - 3
    if room < 1:
        # the ends alone do not fit; the timestamp and the digest still name it
        return f"{ts}_{digest}"[:PLAN_NAME_MAX]
    return f"{ts}_{where[:room]}_{digest}_{function}"


def cmd_run_project(args) -> None:
    with reporting(
        args, "run-project", args.project, suite=pointers.suite_of_project(args.project)
    ):
        members = pointers.project_group(args.project)
        monitor = bool(getattr(args, "monitor", False))
        if members is not None:
            lanes.dispatch(
                f"run-project group '{args.project}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "run-project",
                            "--project",
                            m,
                            *(["--monitor"] if monitor else []),
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
        ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rep().plan(len(inst.triggers) + (1 if monitor else 0))

        def _trigger(t):
            with rep().step(
                "trigger-fn", f"{args.project}/{t.collection}/{t.function}"
            ) as step:
                plan = plan_name(ts, inst.name, args.project, t.function)
                cmd = [
                    "fn",
                    "trigger",
                    "--proj",
                    args.project,
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

        for batch in trigger_batches(inst.triggers):
            lanes.parallel(batch, _trigger)
        if monitor:
            with rep().step("monitor", args.project):
                monitor_trx(args.project)


def cmd_monitor_project(args) -> None:
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
        rep().plan(1)
        with rep().step("monitor", args.project):
            monitor_trx(args.project)


def ns(**kw) -> argparse.Namespace:
    return argparse.Namespace(**kw)
