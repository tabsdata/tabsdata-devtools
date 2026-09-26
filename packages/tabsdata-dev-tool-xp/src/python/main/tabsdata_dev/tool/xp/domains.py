#
# Copyright 2026 Tabsdata Inc.
#
"""The domains phase: ONE `tdd domain create --manifest` off a manifest this
run writes to its scratch dir -- the toolkit's own batch entry point, which
runs every entry in parallel, heaviest backend first, chaining create ->
create-model -> create-data. Teardown is `destroy --manifest`. Domains already
in the store are left alone.
"""

from __future__ import annotations

import getpass
import hashlib
import json
import os
import pathlib
import re
import subprocess

import yaml

from tabsdata_dev.common.core import proc

from . import lanes, pointers, shell, state
from .reporter import rep, reporting, scratch

# A suite domain's `data` size LABEL -> `create-data --size` multiplier
# (xs=100 rows, s=1k, m=10k, l=100k, xl=1M; --size N loads N x ~100 rows).
DATA_SIZE_MULT = {"xs": 1, "s": 10, "m": 100, "l": 1000, "xl": 10000}


def size_multiplier(label: str) -> int:
    mult = DATA_SIZE_MULT.get(label)
    if mult is None:
        state.die(
            f"unknown data size {label!r}; expected one of {', '.join(DATA_SIZE_MULT)}"
        )
    return mult  # type: ignore[return-value]


def run_user() -> str:
    """The run's user id, as `domain` derives its own names: $TD_BUILD_USER if
    set, else the OS login, squeezed to an identifier-safe token."""
    try:
        login = getpass.getuser()
    except Exception:  # noqa: BLE001 -- no controlling user (odd CI)
        login = os.environ.get("USER") or os.environ.get("USERNAME") or "user"
    user = os.environ.get("TD_BUILD_USER") or login
    return re.sub(r"[^A-Za-z0-9_]+", "_", user).strip("_") or "x"


def name_in_system(inst, d, run_ts: str) -> str:
    """``xp_<user>_<ts>_<tag>_<domain>`` -- the BACKEND container name for a
    domain whose descriptor does not pin one. Short on purpose (Postgres's
    63-byte identifier limit); <tag> is 6 hex of the LOGICAL domain name
    (`<instance>_<domain>`), what makes the name unique across the lanes of a
    fan-out that start in the same second with the same domain vocabulary. A
    hash rather than a random tag keeps it stable, so re-running create-domains
    after a partial failure reuses the container instead of orphaning it."""
    tag = hashlib.blake2s(
        inst.domain_full(d.name).encode("utf-8"), digest_size=3
    ).hexdigest()
    return f"xp_{run_user()}_{run_ts}_{tag}_{d.name}"


def domain_entry(inst, d, run_ts: str) -> dict:
    """The manifest entry for one suite domain: `name`, `sys`, `name-in-system`
    (the manifest keys `tdd domain create --manifest` takes), plus `model`/`size`."""
    entry = {
        "name": inst.domain_full(d.name),
        "sys": d.system,
        "name-in-system": d.name_in_system or name_in_system(inst, d, run_ts),
    }
    if d.model:
        entry["model"] = d.model
        entry["size"] = size_multiplier(d.data or "xs")
    return entry


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
    report = scratch() / f"domains-{verb}-report.json"
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
    from .reporter import RUN_TS

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
        rep().plan(len(inst.domains))
        stored = shell.stored_domains()
        todo = []
        for d in inst.domains:
            full = inst.domain_full(d.name)
            if full in stored:
                with rep().step("create-domain", full) as step:
                    step["note"] = "exists"
            else:
                todo.append(d)
        if not todo:
            return
        manifest = write_manifest(
            "domains.yaml", [domain_entry(inst, d, RUN_TS) for d in todo]
        )
        run_manifest(
            "create",
            manifest,
            [inst.domain_full(d.name) for d in todo],
            ["--fail-fast"],
        )


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
