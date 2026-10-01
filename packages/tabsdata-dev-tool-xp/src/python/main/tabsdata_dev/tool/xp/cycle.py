#
# Copyright 2026 Tabsdata Inc.
#
"""The whole-cycle verbs: ``run-suite`` (the suite's stages, in order),
``one-shot`` (create-instance -> run-suite, then tear down unless --keep or
something failed) and ``bench``
(a suite DIR, phased and timed across all lanes).
"""

from __future__ import annotations

import json
import shlex
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from tabsdata_dev.common.core import batch as core_batch

from . import (
    domains,
    execute,
    ids,
    lanes,
    live,
    pointers,
    project,
    shell,
    state,
    suites,
)
from .models import build_instance
from .project import ns
from .reporter import rep, reporting, scratch


def _profile_hint() -> str:
    """The --profile a printed follow-up command needs to reach this run's server."""
    return "".join(f" {shlex.quote(w)}" for w in shell.profile_flag())


# Stages that talk to the project: the first of them creates it.
_PROJECT_STAGES = ("collections", "functions", "triggers", "monitor", "sentinel")


def suite_steps(inst, no_live: bool) -> int:
    """How many steps run-suite reports over `inst`'s stages: what each stage's
    phase plans, the project it creates, and the live calls, which no phase
    plans."""
    steps = int(any(s.kind in _PROJECT_STAGES for s in inst.stages))
    for s in inst.stages:
        if s.kind == "domain-manifest":
            steps += len(s.domain_manifest.domains)
        elif s.kind == "collections":
            groups = {c.group for c in s.collections} - project.BUILTIN_GROUPS
            steps += len(groups) + len(s.collections)
        elif s.kind == "monitor":
            steps += 1
        elif s.kind == "live":
            steps += 0 if no_live else live.count(s.live)
        else:
            steps += len(getattr(s, s.kind))
    return steps


def suite_notes(inst, project_name: str, no_live: bool) -> list[str]:
    """The notes run-suite's steps over `inst` are known to carry before they
    run: the live calls' labels, the collections' types, the sentinels' keys,
    a disabled function's, a check's that goes on failing and a trigger's plan,
    named by a timestamp of the length its own will have. What a step finds out
    as it runs is known only then."""
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    notes: list[str] = []
    for s in inst.stages:
        notes += [
            f"plan={project.plan_name(ts, inst.name, project_name, t.function)}"
            + ("" if t.detached else ", gated")
            for t in s.triggers
        ]
        if s.kind == "live" and not no_live:
            notes += live.labels(s.live)
        notes += [c.type for c in s.collections]
        notes += [x.wait_for_key for x in s.sentinel]
        notes += ["disabled" for f in s.functions if not f.enabled]
        notes += ["continue_on_fail" for e in s.execute if e.continue_on_fail]
    return notes


def cmd_run_suite(args) -> None:
    """Run the instance's stages in the order the suite lists them. A live
    stage's background entries keep running through the stages after it; the
    suite's end waits for them. A suite dir runs one lane per definition, each
    through its own stages, in parallel."""
    no_live = bool(getattr(args, "no_live", False))
    force = bool(getattr(args, "force", False))
    if not getattr(args, "project", None):
        args.project = project.default_project(args.suite_run)
    with reporting(
        args,
        "run-suite",
        args.project,
        suite=pointers.suite_of_instance(args.suite_run),
    ):
        members = pointers.instance_group(args.suite_run)
        if members is not None:
            pairs = [
                (m, f"{args.project}_{lanes.lane_of(args.suite_run, m)}")
                for m in members
            ]
            # Written first: a failed lane is torn down through this pointer.
            pointers.write_group_project(args.project, [mp for _, mp in pairs])
            plans = {}
            for mi, mp in pairs:
                try:
                    member = pointers.load_instance(mi)
                except state.XpError:
                    # Read when the group was made, so the file changed since:
                    # its lane fails on the same, and is counted if it reports.
                    continue
                plans[mp] = lanes.LanePlan(
                    suite_steps(member, no_live),
                    tuple(suite_notes(member, mp, no_live)),
                )
            lanes.dispatch(
                f"run-suite group '{args.project}'",
                [
                    (
                        mp,
                        lanes.child_argv(
                            "run-suite",
                            "--suite-run",
                            mi,
                            "--project",
                            mp,
                            "--secret-env",
                            state.run.secret_env,
                            *(["--no-live"] if no_live else []),
                            *(["--force"] if force else []),
                            *shell.profile_flag(),
                            *shell.dry_flag(),
                        ),
                    )
                    for mi, mp in pairs
                ],
                phase="suite",
                base=args.project,
                plans=plans,
            )
            return
        inst = pointers.load_instance(args.suite_run)
        domains.require_crypto_key()
        _say_ids(inst)
        (scratch() / "suite.resolved.json").write_text(
            json.dumps(inst.doc, indent=2) + "\n", encoding="utf-8"
        )
        # A check script reads the project through tdk, so it needs the login
        # too -- but not the project made on its account.
        if any(s.kind in (*_PROJECT_STAGES, "execute") for s in inst.stages):
            shell.require_login()
            project.claim_project(args.project, args.suite_run, force)
        pointers.write_project(args.project, args.suite_run)
        session = live.Session(inst, args.project)
        rep().reserve(
            suite_steps(inst, no_live), suite_notes(inst, args.project, no_live)
        )
        made = False
        deferred = 0  # scripts that failed with continue_on_fail
        try:
            for stage in inst.stages:
                i = stage.at
                session.check()
                if stage.kind in _PROJECT_STAGES and not made:
                    project.ensure_project(inst, args.project)
                    made = True
                if stage.kind == "domain-manifest":
                    domains.create_from_manifest(
                        inst, stage.domain_manifest, i, args.project
                    )
                elif stage.kind == "domains":
                    domains.create_domains(inst, stage.domains, args.project)
                elif stage.kind == "collections":
                    project.create_collections(inst, args.project, stage.collections)
                elif stage.kind == "functions":
                    project.register_functions(inst, args.project, stage.functions)
                elif stage.kind == "triggers":
                    project.fire_triggers(inst, args.project, stage.triggers)
                elif stage.kind == "monitor":
                    project.watch(args.project, stage.monitor)
                elif stage.kind == "sentinel":
                    project.wait_sentinels(args.project, stage.sentinel)
                elif stage.kind == "execute":
                    deferred += execute.run_scripts(inst, args.project, stage.execute)
                elif no_live:
                    rep().note(f"stage {i}: live skipped (--no-live)")
                else:
                    session.stage(stage.live)
        except BaseException as exc:
            session.abort(exc)
            raise
        session.finish()
        rep().release()
        _say_ids(inst)
        if deferred:
            state.die(
                f"{deferred} check script(s) failed (continue_on_fail let the "
                "suite run on) -- see the execute steps above"
            )


def _say_ids(inst) -> None:
    """The run's IDs, at its start and at its end: what names its domains (and,
    unless --project said, its project), and what names them in the systems."""
    rep().note(f"xp id {inst.xp_id}, short id {inst.short_id}")


def cmd_one_shot(args) -> None:
    """Create the suite run (--suite-run, else its XP_ID) and run its stages in
    order (`run-suite`) on its project (--project, else <XP_ID>_<suite>), then
    tear down. A FAILED run stops before teardown, leaving the setup in place
    for debugging."""
    # Fail fast, before any pointer or domain: every lane's domains phase needs
    # the key, and it is checked first because it costs nothing.
    domains.require_crypto_key()
    shell.require_login()
    suites_dir = getattr(args, "suites_dir", None)
    path, files = suites.resolve(args.suite, suites.suites_dir(suites_dir))
    senv = state.run.secret_env
    with reporting(args, "one-shot", None, suite=suites.label(path)):
        name, path, files = project.create_suite_run(
            args.suite, suites_dir, getattr(args, "suite_run", None)
        )
        proj = args.project or project.default_project(name)
        run_ids = pointers.ids_of(name) or ("", "")
        rep().target = name
        rep().note(
            f"one-shot: suite {path} -> suite run '{name}' ({run_ids[0]}, short "
            f"{run_ids[1]}), project '{proj}'"
        )
        # A suite dir fanned out: track the lanes across the phases so a broken
        # suite file costs only its own lane.
        if files is not None:
            state.run.lanes = {}
        cmd_run_suite(
            ns(
                suite_run=name,
                project=proj,
                secret_env=senv,
                force=getattr(args, "force", False),
                no_live=getattr(args, "no_live", False),
            )
        )

        dead = state.run.lanes or {}
        state.run.lanes = None
        if dead:
            for lane, phase in sorted(dead.items()):
                rep().note(f"{lane} failed in phase '{phase}'")
            rep().note(
                f"one-shot: keeping '{name}' for debugging -- tear down with "
                f"`tdd xp destroy-project --project {proj} --force{_profile_hint()}`, "
                f"`tdd xp destroy-domains --suite-run {name} --force`, "
                f"`tdd xp destroy-instance --suite-run {name}`"
            )
            state.die(f"{len(dead)} lane(s) failed")
        if args.keep:
            rep().note(
                f"one-shot: keeping suite run '{name}' and project '{proj}' -- re-run with `tdd xp run-triggers --project {proj} --monitor --time-out 30m{_profile_hint()}`"
            )
            return
        rep().note(f"one-shot: tearing down '{name}' (use --keep to preserve)")
        project.cmd_destroy_project(ns(project=proj, force=True))
        domains.cmd_destroy_domains(ns(suite_run=name, secret_env=senv, force=True))
        project.cmd_destroy_instance(ns(suite_run=name))


def _await_lane(proj: str) -> tuple[float, int, int]:
    """Block until every transaction in `proj` finishes; (seconds, trx, failed)."""
    argv = shell.tdk_argv("trx", "list", "--proj", proj, "--monitor")
    if state.run.dry_run:
        shell.dry_echo(argv)
        return 0.0, 0, 0
    t0 = time.perf_counter()
    r = shell.run_cmd(argv, check=False)
    trx = shell.tdk(["trx", "list", "--proj", proj], check=False) or []
    failed_n = len(
        [
            t
            for t in trx
            if project.trx_status(str(t.get("status", ""))) in project.FAILED_TRX
        ]
    )
    if r.returncode != 0:
        failed_n = max(1, failed_n)  # an unwatched lane is never a success
    return round(time.perf_counter() - t0, 2), len(trx), failed_n


def cmd_bench(args) -> None:
    """Phased, timed run of a whole suite DIR: (1) every lane's domains, (2)
    every lane's project + collections + functions, (3) every lane's triggers
    at once, (4) await all transactions -- each phase's wall time reported as it
    closes. --report FILE writes the metrics as JSON. An all-green bench tears
    the group down unless --keep; a failed lane keeps everything standing."""
    path, files = suites.resolve(
        args.suite, suites.suites_dir(getattr(args, "suites_dir", None))
    )
    if files is None:
        state.die(
            f"bench needs a suite DIR with one or more descriptors; {args.suite!r} is a single descriptor -- use `one-shot --suite {args.suite}`"
        )
    domains.require_crypto_key()
    shell.require_login()
    started = datetime.now(timezone.utc)
    base_ids = ids.new()
    base = args.name or base_ids[0]
    selector = suites.label(path)

    with reporting(args, "bench", base, suite=selector):
        rep().note(f"bench: suite dir {path} -> base '{base}' ({len(files)} lanes)")
        lane_docs: list[dict] = []
        for definition in files:  # type: ignore[union-attr]
            nm = definition.stem
            name = f"{base}_{nm}"
            # A lane is a suite run of its own, a second after the last.
            lane_ids = ids.new()
            inst = build_instance(name, definition, *lane_ids)
            pointers.write_instance(name, definition, lane_ids)
            lane_docs.append(
                {
                    "lane": nm,
                    "file": str(definition),
                    "instance": name,
                    "xp_id": lane_ids[0],
                    "project": f"{lane_ids[0]}_{suites.token(definition)}",
                    "counts": {
                        "domains": len(inst.domains),
                        "collections": len(inst.collections),
                        "functions": len(inst.functions),
                        "triggers": len(inst.triggers),
                    },
                    "phases": {},
                    "status": "ok",
                }
            )
        pointers.write_group_instance(
            base, [ln["instance"] for ln in lane_docs], path, base_ids
        )

        phase_wall: dict[str, float] = {}
        stopped: str | None = None

        def phase(title: str, key: str, argv_of: Callable[[dict], list[str]]) -> None:
            nonlocal stopped
            if stopped:
                rep().note(
                    f"phase {key}: {title} -- skipped (--fail-fast: phase '{stopped}' had failures)"
                )
                return
            alive = [ln for ln in lane_docs if ln["status"] == "ok"]
            rep().note(f"phase {key}: {title} -- {len(alive)} lane(s)")
            t0 = time.perf_counter()
            if alive:
                dead = lanes.dispatch(
                    f"bench {key}",
                    [(ln["lane"], argv_of(ln)) for ln in alive],
                    fatal=False,
                )
                for ln in alive:
                    ok = ln["lane"] not in dead
                    ln["phases"][key] = {"ok": ok}
                    if not ok:
                        ln["status"] = f"failed:{key}"
            wall = round(time.perf_counter() - t0, 2)
            phase_wall[key] = wall
            rep().note(f"-> {key} wall {wall}s")
            if state.run.fail_fast and any(
                ln["status"] == f"failed:{key}" for ln in lane_docs
            ):
                stopped = key

        senv = state.run.secret_env
        phase(
            "provision domains",
            "domains",
            lambda ln: lanes.child_argv(
                "create-domains",
                "--suite-run",
                ln["instance"],
                "--secret-env",
                senv,
                *shell.dry_flag(),
            ),
        )
        phase(
            "create projects + collections + functions",
            "provision",
            lambda ln: lanes.child_argv(
                "create-project",
                "--suite-run",
                ln["instance"],
                "--project",
                ln["project"],
                "--secret-env",
                senv,
                *shell.profile_flag(),
                *shell.dry_flag(),
            ),
        )
        pointers.write_group_project(base, [ln["project"] for ln in lane_docs])
        phase(
            "fire triggers (all lanes at once)",
            "triggers",
            lambda ln: lanes.child_argv(
                "run-triggers",
                "--project",
                ln["project"],
                *shell.profile_flag(),
                *shell.dry_flag(),
            ),
        )
        _bench_await(lane_docs, phase_wall, stopped)

        ok = [ln for ln in lane_docs if ln["status"] == "ok"]
        bad = [ln for ln in lane_docs if ln["status"] != "ok"]
        total_wall = round((datetime.now(timezone.utc) - started).total_seconds(), 2)
        rep().note(
            f"bench summary: {len(ok)}/{len(lane_docs)} lanes ok, total {total_wall}s"
        )
        for ln in lane_docs:
            rep().note(f"{ln['lane']:24} {ln['status']}")
        rep().note(
            "phase walls: " + ", ".join(f"{k}={v}s" for k, v in phase_wall.items())
        )
        if stopped:
            rep().note(
                f"aborted after phase '{stopped}' (--fail-fast) -- {len(ok)} lane(s) did not run the remaining phases"
            )
        metrics = {
            "base": base,
            "phase_wall_seconds": phase_wall,
            "total_wall_seconds": total_wall,
            "lanes_total": len(lane_docs),
            "lanes_ok": len(ok),
            "lanes_failed": len(bad),
            "aborted_after": stopped,
            "lanes": lane_docs,
        }
        rep().extra["bench"] = metrics
        (scratch() / "bench.json").write_text(
            json.dumps(
                {"suite": selector, "started_at": started.isoformat(), **metrics},
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

        if bad:
            rep().note(
                f"bench: keeping '{base}' -- {len(bad)} lane(s) failed; tear down with "
                f"`tdd xp destroy-project --project {base} --force{_profile_hint()}`, "
                f"`tdd xp destroy-domains --suite-run {base} --force`, "
                f"`tdd xp destroy-instance --suite-run {base}`"
            )
            state.die(f"{len(bad)} of {len(lane_docs)} lane(s) failed")
        if args.keep:
            rep().note(
                f"bench: keeping '{base}' -- re-run with `tdd xp run-triggers --project {base} --monitor --time-out 30m{_profile_hint()}`"
            )
            return
        rep().note(f"bench: tearing down '{base}' (use --keep to preserve)")
        project.cmd_destroy_project(ns(project=base, force=True))
        domains.cmd_destroy_domains(ns(suite_run=base, secret_env=senv, force=True))
        project.cmd_destroy_instance(ns(suite_run=base))


def _bench_await(
    lane_docs: list[dict], phase_wall: dict[str, float], stopped: str | None
) -> None:
    """bench's fourth barrier: every still-alive lane's transactions, in
    parallel, one reported step each -- and every lane's outcome, so this is
    not the fail-fast `parallel`."""
    if stopped:
        rep().note(
            f"phase completion: await transactions -- skipped (--fail-fast: phase '{stopped}' had failures)"
        )
        return
    alive = [ln for ln in lane_docs if ln["status"] == "ok"]
    rep().note(f"phase completion: await transactions -- {len(alive)} lane(s)")
    rep().plan(len(alive))
    t0 = time.perf_counter()

    def _await(ln):
        with rep().step("await-trx", ln["project"]) as step:
            secs, total, failed = _await_lane(ln["project"])
            ln["phases"]["completion"] = {
                "seconds": secs,
                "ok": failed == 0,
                "trx": total,
                "failed": failed,
            }
            step["note"] = f"trx={total} failed={failed}"
            if failed:
                ln["status"] = "failed:completion"
                state.die(
                    f"{failed} of {total} transaction(s) failed in '{ln['project']}'"
                )

    with ThreadPoolExecutor(
        max_workers=max(1, min(len(alive), core_batch.parallelism()))
    ) as pool:
        for future in [pool.submit(_await, ln) for ln in alive]:
            try:
                future.result()
            except BaseException:  # noqa: BLE001 -- recorded on the lane, reported above
                pass
    phase_wall["completion"] = round(time.perf_counter() - t0, 2)
    rep().note(f"-> completion wall {phase_wall['completion']}s")
