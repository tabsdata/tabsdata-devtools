#
# Copyright 2026 Tabsdata Inc.
#

"""xp -- run tabsdata example suites (the tabsdata-xp repo's tdx-xp, ported).

A SUITE is a JSON definition -- domains, collections, functions, triggers --
living in a dir with its ``functions/``; ``connections/`` templates sit at the
XP root above. The suites ship inside this package and are the default;
``--suites-dir DIR`` looks them up elsewhere (``export-suites --dir DIR`` copies
the built-in ones out). ``--suite <type>/<name>`` names one definition (one
lane), ``--suite <type>`` a suite DIRECTORY (one lane per definition in it, run
in parallel). An INSTANCE is a
named use of a suite (its domains are prefixed with the instance name); a
PROJECT is created on the server from an instance. Pointers live under
``<tdd_dir>/data/xp``; each run's manifests, logs and report land in one
scratch dir under ``/tmp/tdd-xp/``, announced at startup.

tdk runs inside the managed venv `tdd venv` activated (``tdd tdk``, so
``_TDD_VENV`` must be set); domains are provisioned by ``tdd domain`` off a
manifest this tool writes.

    tdd xp list-suites [--suites-dir DIR]
    tdd xp export-suites --dir DIR [--force]
    tdd xp list-instances | list-projects
    tdd xp create-instance  --suite SEL --instance I [--suites-dir DIR]
    tdd xp create-domains   --instance I [--secret-env VAR] [--latch F] [--report F] [--dry-run]
    tdd xp destroy-domains  --instance I [--force] ...
    tdd xp create-project   --instance I --project P ...
    tdd xp destroy-project  --project P [--force] ...
    tdd xp destroy-instance --instance I
    tdd xp run-project      --project P [--monitor] ...
    tdd xp monitor-project  --project P ...
    tdd xp one-shot         --suite SEL [--project P] [--keep] [--fail-fast] [--suites-dir DIR] ...
    tdd xp bench            --suite TYPE [--name N] [--keep] [--fail-fast] [--suites-dir DIR] ...
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from tabsdata_dev.common.core import cli
from tabsdata_dev.common.core import latch as core_latch
from tabsdata_dev.common.core import render

from . import cycle, domains, project, state
from .reporter import render_summary

NAME = state.TOOL
DESCRIPTION = "run tabsdata example suites: instances, domains, projects, triggers, one-shot and bench"
SUITE_HELP = (
    "<type>/<name> (one definition) or <type> (a suite dir: one instance/project per *.json "
    "in it), under the built-in suites or --suites-dir; a path works too"
)


# --------------------------------------------------------------- parser ----
def _common(c: argparse.ArgumentParser) -> None:
    """--format / --verbose on a subcommand too, so they may follow the verb;
    SUPPRESS keeps a subparser default from overwriting the top-level value."""
    c.add_argument(
        "--format",
        choices=("json", "view"),
        default=argparse.SUPPRESS,
        help="json is JSON Lines, one event per line (default: view)",
    )
    c.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show debug events too",
    )


def _secret_env(c):
    c.add_argument(
        "--secret-env",
        metavar="VAR",
        default=state.DEFAULT_SECRET_ENV,
        help=f"env var holding the domain crypto key, mapped into {state.DEFAULT_SECRET_ENV} for `tdd domain` (default: {state.DEFAULT_SECRET_ENV})",
    )


def _force(c):
    c.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="carry on (warn) when a backend teardown fails, still removing the local pointer",
    )


def _latch(c):
    c.add_argument(
        "--latch",
        metavar="FILE",
        default=None,
        help="on completion touch FILE.ok or FILE.err, then FILE -- for a background waiter",
    )


def _report(c):
    c.add_argument(
        "--report",
        metavar="FILE",
        default=None,
        help="also write the run's JSON report (every step with its wall seconds and outcome) to FILE; always written to report.json in the scratch dir",
    )


def _fail_fast(c):
    c.add_argument(
        "--fail-fast",
        action="store_true",
        help="abort the whole run at the first phase in which a lane fails, instead of dropping that lane and carrying on (only bites when --suite is a DIR)",
    )


def _dry_run(c):
    c.add_argument(
        "--dry-run",
        action="store_true",
        help="print ONLY the tdd tdk / tdd domain commands that would run, one paste-ready line each, without executing any; no login needed, reads skipped",
    )


def _suite(c, help_: str):
    c.add_argument("--suite", required=True, metavar="SELECTOR", help=help_)
    _suites_dir(c)


def _suites_dir(c):
    c.add_argument(
        "--suites-dir",
        metavar="DIR",
        default=None,
        help="look --suite up under DIR instead of the built-in suites (export-suites writes a copy)",
    )


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    c = sub.add_parser(
        "list-suites",
        help="list the suite definitions (built-in, or under --suites-dir)",
    )
    _suites_dir(c)
    _common(c)
    c.set_defaults(func=project.cmd_list_suites)

    c = sub.add_parser(
        "list-systems",
        help="the systems a suite's domains need, checked against the tdd system store; fails when one is missing",
    )
    _suite(c, SUITE_HELP)
    for add in (_secret_env, _common):
        add(c)
    c.set_defaults(func=project.cmd_list_systems)

    c = sub.add_parser(
        "export-suites",
        help="copy the built-in suites/ and connections/ into a directory",
    )
    c.add_argument(
        "--dir",
        required=True,
        metavar="DIR",
        help="destination; gets DIR/suites and DIR/connections",
    )
    c.add_argument(
        "--force", "-f", action="store_true", help="overwrite an existing copy"
    )
    _common(c)
    c.set_defaults(func=project.cmd_export_suites)

    c = sub.add_parser(
        "list-instances", help="list the instances recorded in the pointer store"
    )
    _common(c)
    c.set_defaults(func=project.cmd_list_instances)

    c = sub.add_parser(
        "list-projects", help="list the projects recorded in the pointer store"
    )
    _common(c)
    c.set_defaults(func=project.cmd_list_projects)

    c = sub.add_parser("create-instance", help="materialise an instance from a suite")
    _suite(c, SUITE_HELP)
    c.add_argument(
        "--instance", required=True, help="instance name (group base for a suite dir)"
    )
    _common(c)
    c.set_defaults(func=project.cmd_create_instance)

    c = sub.add_parser(
        "create-domains",
        help="create the instance's domains (prefixed with the instance name)",
    )
    c.add_argument("--instance", required=True)
    for add in (_secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=domains.cmd_create_domains)

    c = sub.add_parser("destroy-domains", help="destroy the instance's domains")
    c.add_argument("--instance", required=True)
    for add in (_force, _secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=domains.cmd_destroy_domains)

    c = sub.add_parser(
        "create-project", help="create the project, its collections and functions"
    )
    c.add_argument("--instance", required=True)
    c.add_argument("--project", required=True)
    for add in (_secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_create_project)

    c = sub.add_parser(
        "destroy-project",
        help="delete the project (instance resolved from the project pointer)",
    )
    c.add_argument("--project", required=True)
    for add in (_force, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_destroy_project)

    c = sub.add_parser(
        "destroy-instance", help="remove the local instance pointer (not its domains)"
    )
    c.add_argument("--instance", required=True)
    _common(c)
    c.set_defaults(func=project.cmd_destroy_instance)

    c = sub.add_parser(
        "run-project", help="trigger the instance's functions on the project"
    )
    c.add_argument("--project", required=True)
    c.add_argument(
        "--monitor",
        action="store_true",
        help="after triggering, watch the transactions until they finish",
    )
    for add in (_latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_run_project)

    c = sub.add_parser(
        "monitor-project", help="watch a project's transactions until they finish"
    )
    c.add_argument("--project", required=True)
    for add in (_report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_monitor_project)

    c = sub.add_parser(
        "one-shot",
        help="create-instance + domains + project + run --monitor, then tear down (--keep preserves)",
    )
    _suite(c, SUITE_HELP)
    c.add_argument(
        "--project",
        default=None,
        help="name for the instance/project (default: xp_<ts>_<suite>)",
    )
    c.add_argument(
        "--keep",
        action="store_true",
        help="leave the instance, project and domains set up afterwards",
    )
    for add in (_fail_fast, _secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=cycle.cmd_one_shot)

    c = sub.add_parser(
        "bench",
        help="phased, timed run of a whole suite dir, one lane per file, then tear down (--keep preserves)",
    )
    _suite(
        c,
        "a suite dir <type> (each *.json in it is a swim lane); a single definition is rejected -- use one-shot",
    )
    c.add_argument(
        "--name",
        default=None,
        help="group base name for the per-lane instances/projects (default xp_<ts>_<suite>)",
    )
    c.add_argument(
        "--keep",
        action="store_true",
        help="leave every lane's setup afterwards; a bench with a failed lane is kept regardless",
    )
    for add in (_fail_fast, _secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=cycle.cmd_bench)


# ----------------------------------------------------------------- body ----
def body(args: argparse.Namespace, out: render.Renderer) -> int:
    state.bind(out, args)
    latch = pathlib.Path(args.latch) if getattr(args, "latch", None) else None
    if latch is not None:
        core_latch.clear(latch)
    rc = 1
    try:
        try:
            result = args.func(args)
        except state.XpError as exc:
            rc = _fail(out, str(exc))
            return rc
        except KeyboardInterrupt:
            rc = _fail(out, "interrupted")
            return rc
        doc = state.run.summary
        if doc is not None:
            rc = out.ok(render_summary(doc), xp="summary", **_public(doc))
        else:
            message, fields = result if result else ("done", {})
            rc = out.ok(message, **fields)
        return rc
    finally:
        if latch is not None:
            core_latch.touch(latch, ok=(rc == 0))


def _fail(out: render.Renderer, message: str) -> int:
    doc = state.run.summary
    if doc is None:
        return out.error(message)
    # The run kept its own log of every command; the failure block goes there too.
    details = f"see {doc.get('errors') or doc.get('run_log')}"
    return out.error(
        f"{message}\n{render_summary(doc)}",
        details=details,
        log=doc.get("run_log"),
        xp="summary",
        **_public(doc),
    )


def _public(doc: dict) -> dict:
    return {k: v for k, v in doc.items() if k != "detail"}


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[attr-defined]
        except (AttributeError, ValueError):
            pass
    return cli.run(NAME, DESCRIPTION, body, configure=configure)


if __name__ == "__main__":
    sys.exit(main())
