#
# Copyright 2026 Tabsdata Inc.
#
"""The domains phase: a domains stage's `tdd domain` calls -- each domain's
create, then what fills it -- one step per call, each domain's calls in order
and the domains side by side. Domains already in the store are left alone.
Teardown is one `tdd domain destroy --manifest` over every suite domain.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import pathlib
import re
import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import yaml

from tabsdata_dev.common.core import batch as core_batch
from tabsdata_dev.common.core import proc

from . import lanes, pointers, shell, state, work
from .reporter import rep, reporting, scratch


def run_user() -> str:
    """The run's user id, as `domain` derives its own names: $TD_BUILD_USER if
    set, else the OS login, squeezed to an identifier-safe token."""
    try:
        login = getpass.getuser()
    except Exception:  # noqa: BLE001 -- no controlling user (odd CI)
        login = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    user = os.environ.get("TD_BUILD_USER") or login
    return re.sub(r"[^A-Za-z0-9_]+", "_", user).strip("_") or "x"


def name_in_system(inst, name: str, run_ts: str) -> str:
    """``xp_<user>_<ts>_<tag>_<domain>`` -- the BACKEND name xp gives a domain's
    create (``--name-in-system``). Short on purpose (Postgres's 63-byte
    identifier limit); <tag> is 6 hex of the LOGICAL domain name
    (`<instance>_<domain>`), what makes the name unique across the lanes of a
    fan-out that start in the same second with the same domain vocabulary. A
    hash rather than a random tag keeps it stable, so re-running create-domains
    after a partial failure reuses the container instead of orphaning it."""
    tag = hashlib.blake2s(
        inst.domain_full(name).encode("utf-8"), digest_size=3
    ).hexdigest()
    return f"xp_{run_user()}_{run_ts}_{tag}_{name}"


def call_argv(inst, call, project: str | None = None) -> list[str]:
    """`tdd domain <command> --domain <instance>_<name> <options...>` for a
    domain call, its tokens expanded; a create also gets the run's backend name."""
    from .reporter import RUN_TS

    options = [work.expand(o, project) for o in call.options]
    if call.command == "create":
        options += ["--name-in-system", name_in_system(inst, call.name, RUN_TS)]
    return proc.tool_argv(
        "domain", call.command, "--domain", inst.domain_full(call.name), *options
    )


def run_call(argv: list[str], action: str, path: str, where: str) -> None:
    """One `tdd domain` call as one step; a failure ends the run with what the
    command said."""
    with rep().step(action, path) as step:
        step["note"] = where
        if state.run.dry_run:
            shell.dry_echo(argv)
            return
        r = shell.run_cmd(
            [*argv, "--format", "json"], check=False, env=shell.domain_env()
        )
        if r.returncode != 0:
            final = shell.last_event(r.stdout) or {}
            why = str(final.get("message") or shell.last_err(r)).splitlines()
            state.die(
                f"{shell.shell_line(argv)} exited {r.returncode}"
                + (f": {why[0]}" if why else "")
            )


def write_manifest(name: str, entries: list[dict]) -> pathlib.Path:
    path = scratch() / name
    path.write_text(yaml.safe_dump(entries, sort_keys=False), encoding="utf-8")
    rep().log(f"manifest {path}", path.read_text(encoding="utf-8"))
    return path


def run_manifest(
    verb: str, manifest: pathlib.Path, names: list[str], extra: list[str]
) -> None:
    """Run one `tdd domain <verb> --manifest` child and report a STEP per domain
    as the child finishes it. The child runs with --format json: its batch
    runner emits one event per finished target (fields ``task``, ``status``,
    ``seconds``), which is what makes the domains phase incremental rather than
    one opaque wait. Its --report JSON is the authoritative record for anything
    the stream never mentioned."""
    # One per manifest: a suite with two domains stages writes two.
    report = scratch() / f"{manifest.stem}-{verb}-report.json"
    words = [verb, "--manifest", str(manifest), *extra]
    if verb == "create":
        words += ["--report", str(report)]
    argv = proc.tool_argv("domain", *words)
    if state.run.dry_run:
        shell.dry_echo(argv)
        for name in names:
            with rep().step(f"{verb}-domain", name) as step:
                step["note"] = "dry-run"
        return
    seen: set[str] = set()
    lines: list[str] = []
    p = subprocess.Popen(
        [*argv, "--format", "json"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=shell.domain_env(),
    )
    for raw in p.stdout:  # type: ignore[union-attr]
        line = raw.rstrip("\n")
        lines.append(line)
        if not line.startswith("{"):
            continue
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        task, status = event.get("task"), event.get("status")
        if not task or status not in ("ok", "fail", "skipped"):
            continue
        seen.add(str(task))
        tail = [ln for ln in str(event.get("output", "")).splitlines() if ln.strip()]
        # The child did the work and timed it; replay it with the time IT measured.
        rep().step_done(
            f"{verb}-domain",
            str(task),
            float(event.get("seconds") or 0.0),
            status == "ok",
            note="" if status == "ok" else status,
            error="" if status == "ok" else (tail[-1] if tail else "see run.log"),
        )
    code = p.wait()
    rep().log(f"$ {shell.shell_line(argv)} -> exit {code}", "\n".join(lines))
    recorded = _manifest_report(report) if verb == "create" else {}
    for name in names:
        if name in seen:
            continue
        task = recorded.get(name, {})
        status = task.get("status") or ("ok" if code == 0 else "fail")
        rep().step_done(
            f"{verb}-domain",
            name,
            float(task.get("seconds") or 0.0),
            status != "fail",
            note="" if status == "ok" else status,
            error="see run.log" if status == "fail" else "",
        )
    if code != 0:
        final = shell.last_event("\n".join(lines))
        why = (final or {}).get("message", "").splitlines()[0] if final else ""
        state.die(
            f"tdd domain {verb} --manifest exited {code}"
            + (f": {why}" if why else "")
            + f"\n       full output: {rep().log_path}"
        )


def _manifest_report(path: pathlib.Path) -> dict[str, dict]:
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    tasks = doc.get("tasks") if isinstance(doc, dict) else None
    return {t["name"]: t for t in tasks or [] if isinstance(t, dict) and t.get("name")}


def require_crypto_key() -> None:
    """The domain descriptors are encrypted: without the key no `tdd domain`
    call can read one, and a run would find out one lane at a time."""
    if state.run.dry_run or os.environ.get(state.run.secret_env):
        return
    how = (
        "set it with `tdd env set --crypto` (reads it from 1Password), or export it"
        if state.run.secret_env == state.DEFAULT_SECRET_ENV
        else f"export {state.run.secret_env}, or drop --secret-env to use {state.DEFAULT_SECRET_ENV}"
    )
    state.die(
        f"the domain crypto key is not set: {state.run.secret_env} is empty, and every "
        f"`tdd domain` call needs it to read the encrypted descriptors -- {how}"
    )


def cmd_create_domains(args) -> None:
    with reporting(
        args,
        "create-domains",
        args.instance,
        suite=pointers.suite_of_instance(args.instance),
    ):
        members = pointers.instance_group(args.instance)
        if members is not None:
            lanes.dispatch(
                f"create-domains group '{args.instance}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "create-domains",
                            "--instance",
                            m,
                            "--secret-env",
                            state.run.secret_env,
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="domains",
                base=args.instance,
            )
            return
        inst = pointers.load_instance(args.instance)
        require_crypto_key()
        for s in inst.stages:  # every domain stage of either kind, in order
            if s.domain_manifest is not None:
                create_from_manifest(inst, s.domain_manifest, s.at)
            elif s.domains:
                create_domains(inst, s.domains)


def manifest_entry(inst, d, run_ts: str, emit_file: pathlib.Path | None) -> dict:
    """The `tdd domain create --manifest` entry for one domain-manifest domain:
    `name`, `sys`, `name-in-system`, plus `model`/`size` for a seeded one and
    the `emit-ops` file its create-data appends to."""
    entry: dict = {
        "name": inst.domain_full(d.name),
        "sys": d.system,
        "name-in-system": name_in_system(inst, d.name, run_ts),
    }
    if d.model:
        entry["model"] = d.model
        entry["size"] = d.size
        if emit_file is not None:
            entry["emit-ops"] = str(emit_file)
    return entry


def create_from_manifest(inst, dm, at: int, project: str | None = None) -> None:
    """A domain-manifest stage: its domains through ONE `tdd domain create
    --manifest` -- every domain in parallel, heaviest backend first, one step
    per domain -- leaving those already in the store alone.

    With ``emit_ops``, each seeded domain whose ``emit`` is not false appends
    its seed's operations to a file of its own under the work dir -- domains
    load side by side, and two processes appending to one file with no lock
    can interleave (and on Windows an append is not even atomic). Once the
    batch is done they are appended to ``emit_ops`` in the order listed, so the
    trail is the same whichever domain finished first. A failed batch appends
    nothing; the per-domain files stay behind to look at."""
    from .reporter import RUN_TS

    rep().plan(len(dm.domains))
    stored = shell.stored_domains()
    todo = []
    for d in dm.domains:
        full = inst.domain_full(d.name)
        if full in stored:
            with rep().step("create-domain", full) as step:
                step["note"] = "exists"
        else:
            todo.append(d)
    if not todo:
        return
    emit_dir = work.work_dir() / f"domain-manifest-{at}" if dm.emit_ops else None
    emits: list[pathlib.Path] = []
    entries = []
    for d in todo:
        emit_file = None
        if emit_dir is not None and d.model and d.emit:
            emit_file = emit_dir / f"{d.name}.ops.jsonl"
            emits.append(emit_file)
        entries.append(manifest_entry(inst, d, RUN_TS, emit_file))
    if emit_dir is not None:
        emit_dir.mkdir(parents=True, exist_ok=True)
    path = write_manifest(f"domains-{at}.yaml", entries)
    run_manifest("create", path, [e["name"] for e in entries], ["--fail-fast"])
    if dm.emit_ops and not state.run.dry_run:
        final = pathlib.Path(work.expand(dm.emit_ops, project))
        final.parent.mkdir(parents=True, exist_ok=True)
        with final.open("ab") as out:
            for f in emits:
                if f.is_file():
                    out.write(f.read_bytes())
        rep().log(
            f"appended {len(emits)} seed trail(s) to {final}",
            "\n".join(map(str, emits)),
        )


def _action(command: str) -> str:
    return "create-domain" if command == "create" else command


def create_domains(inst, calls: list, project: str | None = None) -> None:
    """Run a domains stage's calls: each domain's in the order written, the
    domains side by side (bounded by $TDD_PARALLELISM), one step per call. A
    domain whose create finds it already in the store is left alone, the rest
    of its calls with it -- so `run-suite` is safe to run again. The first
    failure stops every domain at its next call and is the run's error."""
    rep().plan(len(calls))
    stored = shell.stored_domains()
    chains: dict[str, list] = {}
    for c in calls:
        chains.setdefault(c.name, []).append(c)
    todo: dict[str, list] = {}
    for name, chain in chains.items():
        full = inst.domain_full(name)
        if chain[0].command == "create" and full in stored:
            for c in chain:
                with rep().step(_action(c.command), full) as step:
                    step["note"] = "exists"
        else:
            todo[name] = chain
    stop = threading.Event()

    def run_chain(name: str, chain: list) -> None:
        for c in chain:
            if stop.is_set():
                return
            run_call(
                call_argv(inst, c, project),
                _action(c.command),
                inst.domain_full(name),
                "",
            )

    if state.run.dry_run or len(todo) < 2:
        # One at a time: the plan prints in suite order.
        for name, chain in todo.items():
            run_chain(name, chain)
        return
    first: BaseException | None = None
    with ThreadPoolExecutor(
        max_workers=min(len(todo), core_batch.parallelism())
    ) as pool:
        futures = [pool.submit(run_chain, n, c) for n, c in todo.items()]
        for future in as_completed(futures):
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 -- the first is the run's
                if first is None:
                    first = exc
                stop.set()
    if first is not None:
        raise first


def cmd_destroy_domains(args) -> None:
    force = bool(getattr(args, "force", False))
    with reporting(
        args,
        "destroy-domains",
        args.instance,
        suite=pointers.suite_of_instance(args.instance),
    ):
        members = pointers.instance_group(args.instance)
        if members is not None:
            lanes.dispatch(
                f"destroy-domains group '{args.instance}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "destroy-domains",
                            "--instance",
                            m,
                            "--secret-env",
                            state.run.secret_env,
                            *(["--force"] if force else []),
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
            )
            return
        inst = pointers.load_instance(args.instance)
        require_crypto_key()
        rep().plan(len(inst.domains))
        stored = shell.stored_domains()
        todo = []
        for d in inst.domains:
            full = inst.domain_full(d.name)
            # In dry-run the existence read is skipped: plan the destroy the run
            # WOULD do instead of reporting everything absent.
            if full in stored or state.run.dry_run:
                todo.append(d)
            else:
                with rep().step("destroy-domain", full) as step:
                    step["note"] = "absent"
        if not todo:
            return
        names = [inst.domain_full(d.name) for d in todo]
        manifest = write_manifest("domains-destroy.yaml", [{"name": n} for n in names])
        # Without --force, domain fails if the backend teardown fails; with it
        # the descriptor is dropped anyway (warns).
        run_manifest("destroy", manifest, names, ["--force"] if force else [])
