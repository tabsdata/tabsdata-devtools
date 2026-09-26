#
# Copyright 2026 Tabsdata Inc.
#
"""The whole-cycle verbs: ``one-shot`` (create-instance -> domains -> project ->
run --monitor [-> live-domains -> monitor], then tear down unless --keep or
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

from . import domains, lanes, live, pointers, project, shell, state, suites
from .models import build_instance
from .project import ns
from .reporter import rep, reporting, scratch


def _profile_hint() -> str:
    """The --profile a printed follow-up command needs to reach this run's server."""
    return "".join(f" {shlex.quote(w)}" for w in shell.profile_flag())


def cmd_one_shot(args) -> None:
    """Pick a name (--project, else xp_<ts>_<suite>) and run the whole cycle
    under it for both the instance and the project. A suite with a live program
    runs it once the triggers have been watched, and is watched again after, for
    the transactions its changes started (unless --no-live). A FAILED run stops
    before teardown, leaving the setup in place for debugging."""
    # Fail fast, before any pointer or domain: every lane's domains phase needs
    # the key, and it is checked first because it costs nothing.
    domains.require_crypto_key()
    shell.require_login()
    suites_dir = getattr(args, "suites_dir", None)
    path, files = suites.resolve(args.suite, suites.suites_dir(suites_dir))
    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
    name = args.project or f"xp_{ts}_{suites.token(path)}"
    senv = state.run.secret_env
    with reporting(args, "one-shot", name, suite=suites.label(path)):
        rep().note(f"one-shot: suite {path} -> instance/project '{name}'")
        project.cmd_create_instance(
            ns(suite=args.suite, instance=name, suites_dir=suites_dir)
        )
        # A suite dir fanned out: track the lanes across the phases so a broken
        # suite file costs only its own lane.
        if files is not None:
            state.run.lanes = {}
        domains.cmd_create_domains(ns(instance=name, secret_env=senv))
        project.cmd_create_project(ns(instance=name, project=name, secret_env=senv))
        project.cmd_run_project(ns(project=name, monitor=True))
        if not getattr(args, "no_live", False) and live.has_live(files or [path]):
            live.cmd_live_domains(ns(instance=name, secret_env=senv))
            project.cmd_monitor_project(ns(project=name))

        dead = state.run.lanes or {}
        state.run.lanes = None
        if dead:
            for lane, phase in sorted(dead.items()):
                rep().note(f"{lane} failed in phase '{phase}'")
            rep().note(
                f"one-shot: keeping '{name}' for debugging -- tear down with "
                f"`tdd xp destroy-project --project {name} --force{_profile_hint()}`, "
                f"`tdd xp destroy-domains --instance {name} --force`, "
                f"`tdd xp destroy-instance --instance {name}`"
            )
            state.die(f"{len(dead)} lane(s) failed")
        if args.keep:
            rep().note(
                f"one-shot: keeping instance/project '{name}' -- re-run with `tdd xp run-project --project {name} --monitor{_profile_hint()}`"
            )
            return
        rep().note(f"one-shot: tearing down '{name}' (use --keep to preserve)")
        project.cmd_destroy_project(ns(project=name, force=True))
        domains.cmd_destroy_domains(ns(instance=name, secret_env=senv, force=True))
        project.cmd_destroy_instance(ns(instance=name))


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
    ts = started.strftime("%Y%m%dT%H%M%S")
    base = args.name or f"xp_{ts}_{suites.token(path)}"
    selector = suites.label(path)

    with reporting(args, "bench", base, suite=selector):
        rep().note(f"bench: suite dir {path} -> base '{base}' ({len(files)} lanes)")
        lane_docs: list[dict] = []
        for definition in files:  # type: ignore[union-attr]
            nm = definition.stem
            name = f"{base}_{nm}"
            inst = build_instance(name, definition)
            pointers.write_instance(name, definition)
            lane_docs.append(
                {
                    "lane": nm,
                    "file": str(definition),
                    "instance": name,
                    "project": name,
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
        pointers.write_group_instance(base, [ln["instance"] for ln in lane_docs], path)

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
                "--instance",
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
                "--instance",
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
                "run-project",
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
                f"`tdd xp destroy-domains --instance {base} --force`, "
                f"`tdd xp destroy-instance --instance {base}`"
            )
            state.die(f"{len(bad)} of {len(lane_docs)} lane(s) failed")
        if args.keep:
            rep().note(
                f"bench: keeping '{base}' -- re-run with `tdd xp run-project --project {base} --monitor{_profile_hint()}`"
            )
            return
        rep().note(f"bench: tearing down '{base}' (use --keep to preserve)")
        project.cmd_destroy_project(ns(project=base, force=True))
        domains.cmd_destroy_domains(ns(instance=base, secret_env=senv, force=True))
        project.cmd_destroy_instance(ns(instance=base))


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
