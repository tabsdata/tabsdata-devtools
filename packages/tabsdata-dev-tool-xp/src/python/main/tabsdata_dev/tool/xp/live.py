#
# Copyright 2026 Tabsdata Inc.
#
"""Live domains: a suite's ``live`` program, run against its domains while the
project is up -- the data changing under the functions the way a real source's
does, so a stream publisher or a re-triggered publisher has something to see.

The program is a list of steps (``models.LiveStep``): `tdd domain` data verbs
with their options, pauses, and groups, any of them repeated with a pause
between repetitions, so loops nest::

    "live": [
      {"repeat": 3, "steps": [
        {"command": "create-data", "domain": "pg"},
        {"repeat": 10, "steps": [
          {"sleep": 1},
          {"command": "modify-data", "domain": "pg", "options": {"sets": 2}},
          {"command": "modify-data", "domain": "pg", "options": {"ops": "Insert"}}
        ]},
        {"command": "delete-data", "domain": "pg"}
      ]}
    ]

Every call is one step of the run, in program order; a command naming several
domains runs one call per domain in parallel, and the first failure stops the
program. ``create-model`` and ``create-data`` default ``--model``/``--size`` to
what the suite's domain declares, so a program that deletes and recreates a
domain's data says only what it changes.
"""

from __future__ import annotations

import time

from tabsdata_dev.common.core import proc

from . import domains, lanes, pointers, shell, state
from .models import Instance, LiveStep
from .reporter import rep, reporting


def count(steps: list[LiveStep]) -> int:
    """How many calls the program makes -- its steps, for the [N/M] total."""
    total = 0
    for s in steps:
        if s.command is not None:
            per = len(s.domains())
        else:
            per = count(s.steps or [])
        total += s.repeat * per
    return total


def argv_of(inst: Instance, s: LiveStep, domain: str) -> list[str]:
    """`tdd domain <command> --domain <instance>_<domain> --<opt> <value>...`,
    the suite domain's model and size filled in where the step left them out."""
    opts = dict(s.options)
    d = inst.domain(domain)
    if s.command == "create-model" and "model" not in opts:
        if not d.model:
            state.die(
                f"live create-model on '{domain}': the step gives no 'model' option and the suite's domain declares none"
            )
        opts["model"] = d.model
    if s.command == "create-data" and "size" not in opts and d.model:
        opts["size"] = domains.size_multiplier(d.data or "xs")
    words = [str(s.command), "--domain", inst.domain_full(domain)]
    for key, value in opts.items():
        if value is False:
            continue
        words.append(f"--{key}")
        if value is not True:
            words.append(str(value))
    return proc.tool_argv("domain", *words)


def _call(argv: list[str], action: str, path: str, where: str) -> None:
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


def _pause(seconds: float) -> None:
    if not seconds:
        return
    if state.run.dry_run:
        shell.dry_echo(["sleep", f"{seconds:g}"])
        return
    rep().log(f"sleep {seconds:g}s")
    time.sleep(seconds)


def run(inst: Instance, steps: list[LiveStep], where: str = "") -> None:
    """Run `steps` in order. `where` is the iteration they run in -- ``2/3``,
    ``2/3.7/10`` -- shown on each call so a progress line says which pass it is."""
    for s in steps:
        for i in range(1, s.repeat + 1):
            if s.command is None and s.steps is None:
                _pause(s.sleep)  # a pause step: the sleep is the step itself
                continue
            if i > 1:
                _pause(s.sleep)
            here = where
            if s.repeat > 1:
                here = f"{where}.{i}/{s.repeat}" if where else f"{i}/{s.repeat}"
            if s.command is not None:
                lanes.parallel(
                    s.domains(),
                    lambda d, s=s, here=here: _call(
                        argv_of(inst, s, d), str(s.command), inst.domain_full(d), here
                    ),
                )
            else:
                run(inst, s.steps or [], here)


def has_live(definitions) -> bool:
    """Whether any of these suite definitions carries a live program."""
    from .models import build_instance

    return any(build_instance("_", d).live for d in definitions)


def cmd_live_domains(args) -> None:
    with reporting(
        args,
        "live-domains",
        args.instance,
        suite=pointers.suite_of_instance(args.instance),
    ):
        members = pointers.instance_group(args.instance)
        if members is not None:
            lanes.dispatch(
                f"live-domains group '{args.instance}'",
                [
                    (
                        m,
                        lanes.child_argv(
                            "live-domains",
                            "--instance",
                            m,
                            "--secret-env",
                            state.run.secret_env,
                            *shell.dry_flag(),
                        ),
                    )
                    for m in members
                ],
                phase="live",
                base=args.instance,
            )
            return
        inst = pointers.load_instance(args.instance)
        if not inst.live:
            rep().note(f"live-domains: suite of '{args.instance}' has no live program")
            return
        domains.require_crypto_key()
        rep().plan(count(inst.live))
        run(inst, inst.live)
