#
# Copyright 2026 Tabsdata Inc.
#

"""xp -- run tabsdata example suites (the tabsdata-xp repo's tdx-xp, ported).

A SUITE is a JSON definition -- an ordered list of stages: domains,
collections, functions, triggers, monitor, actions -- living in a dir with its
``functions/``; ``connections/`` templates sit at the
XP root above. The suites ship inside this package and are the default;
``--suites-dir DIR`` looks them up elsewhere (``export-suites --dir DIR`` copies
the built-in ones out). ``--suite <type>/<name>`` names one definition (one
lane), ``--suite <type>`` a suite DIRECTORY (one lane per definition in it, run
in parallel). A SUITE RUN is one run of a suite, named ``--suite-run`` (by
default its XP_ID, ``xp_<user>_<build>_<YYYYMMDD>T<hhmmss>``): the suite is
resolved for it, so ``${xp:name(x)}`` names its domain ``<XP_ID>_x``; a
PROJECT is created on the server for it, ``<XP_ID>_<suite>`` unless
``--project`` names one. Pointers live under
``<tdd_dir>/data/xp``; each run's manifests, logs and report land in one
scratch dir under ``/tmp/tdd-xp/``, announced at startup.

tdk runs inside the venv last activated, managed by `tdd venv` or not
(``tdd tdk`` picks it and says which), on the connection ``--profile`` names when given
(tdk's own default otherwise), and every fan-out child is handed the same
profile; domains are provisioned by ``tdd domain`` off a
manifest this tool writes.

    tdd xp list-suites [--suites-dir DIR]
    tdd xp export-suites --dir DIR [--force]
    tdd xp list-instances | list-projects
    tdd xp create-instance  --suite SEL [--suite-run R] [--suites-dir DIR]
    tdd xp create-domains   --suite-run R [--secret-env VAR] [--latch F] [--report F] [--dry-run]
    tdd xp destroy-domains  --suite-run R [--force] ...
    tdd xp create-project   --suite-run R [--project P] [--force] [--profile NAME] ...
    tdd xp destroy-project  --project P [--force] [--profile NAME] ...
    tdd xp destroy-instance --suite-run R
    tdd xp run-triggers     --project P [--monitor --time-out T] [--profile NAME] ...
    tdd xp monitor-project  --project P --time-out T [--profile NAME] ...
    tdd xp run-actions      --suite-run R [--project P] [--tags T,...] [--skip-tags T,...] [--dry-run] ...
    tdd xp run-suite        --suite-run R [--project P] [--force] [--tags T,...] [--skip-tags T,...] [--no-actions] [--profile NAME] ...
    tdd xp enable-function  --project P --collection C --function F [--profile NAME]
    tdd xp disable-function --project P --collection C --function F [--profile NAME]
    tdd xp one-shot         --suite SEL|s1,s2|ALL [--suite-run R] [--project P] [--force] [--keep] [--tags T,...] [--skip-tags T,...] [--no-actions] [--profile NAME] [--fail-fast] [--suites-dir DIR] ...
    tdd xp bench            --suite TYPE [--name N] [--keep] [--profile NAME] [--fail-fast] [--suites-dir DIR] ...
"""

from __future__ import annotations

import argparse
import pathlib
import sys

from tabsdata_dev.common.core import cli
from tabsdata_dev.common.core import latch as core_latch
from tabsdata_dev.common.core import render

from . import actions, cycle, domains, project, state
from .reporter import render_summary

NAME = state.TOOL
DESCRIPTION = "run tabsdata example suites: suite runs, domains, projects, triggers, one-shot and bench"
SUITE_HELP = (
    "<type>/<name> (one definition) or <type> (a suite dir: one suite run/project per *.json "
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
        help="abort the whole run at the first phase in which a lane fails, instead of dropping that lane and carrying on (only bites when --suite is a DIR); with a one-shot --suite list or ALL, also start no further selector once one fails",
    )


def _dry_run(c):
    c.add_argument(
        "--dry-run",
        action="store_true",
        help="print ONLY the tdd tdk / tdd domain commands that would run, one paste-ready line each, without executing any; no login needed, reads skipped",
    )


def _profile(c):
    c.add_argument(
        "--profile",
        metavar="NAME",
        default=None,
        help="the tdk connection profile every tdk call uses (tdk COMMAND --profile NAME), so runs from shells on one account do not share a login (default: tdk's own)",
    )


def _selection(c, no_actions: bool = True):
    c.add_argument(
        "--tags",
        default=None,
        metavar="T,...",
        help="run only the actions steps tagged with one of these (a block's tags are its steps')",
    )
    c.add_argument(
        "--skip-tags",
        default=None,
        metavar="T,...",
        help="skip the actions steps tagged with one of these",
    )
    if no_actions:
        c.add_argument(
            "--no-actions",
            action="store_true",
            help="run no actions stage at all",
        )


def _time_out(c, required: bool = False):
    c.add_argument(
        "--time-out",
        required=required,
        default=None,
        metavar="T",
        help="how long the monitor may watch, <VALUE><UNIT> (s, m, h): transactions still running then fail the run",
    )


def _suite_run(c, required: bool = True):
    c.add_argument(
        "--suite-run",
        required=required,
        default=None,
        metavar="R",
        help="the suite run (`list-instances` shows them)"
        if required
        else "the suite run: a pointer holding its XP_ID, reused when it exists (default: a new XP_ID, xp_<user>_<build>_<YYYYMMDD>T<hhmmss>)",
    )


def _project_opt(c):
    c.add_argument(
        "--project",
        default=None,
        metavar="P",
        help="the project (default: <XP_ID>_<suite>); one that exists and is not this suite run's is refused unless --force",
    )
    c.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="delete a --project that exists and is not this suite run's, then create it again",
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
        "list-instances", help="list the suite runs recorded in the pointer store"
    )
    _common(c)
    c.set_defaults(func=project.cmd_list_instances)

    c = sub.add_parser(
        "list-projects", help="list the projects recorded in the pointer store"
    )
    _common(c)
    c.set_defaults(func=project.cmd_list_projects)

    c = sub.add_parser(
        "create-instance",
        help="make a suite run of a suite (an existing one is reused, its XP_ID with it)",
    )
    _suite(c, SUITE_HELP)
    _suite_run(c, required=False)
    _common(c)
    c.set_defaults(func=project.cmd_create_instance)

    c = sub.add_parser(
        "create-domains",
        help="create the suite run's domains",
    )
    _suite_run(c)
    for add in (_secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=domains.cmd_create_domains)

    c = sub.add_parser("destroy-domains", help="destroy the suite run's domains")
    _suite_run(c)
    for add in (_force, _secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=domains.cmd_destroy_domains)

    c = sub.add_parser(
        "create-project", help="create the project, its collections and functions"
    )
    _suite_run(c)
    _project_opt(c)
    for add in (_secret_env, _profile, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_create_project)

    c = sub.add_parser(
        "destroy-project",
        help="delete the project (its suite run resolved from the project pointer)",
    )
    c.add_argument("--project", required=True)
    for add in (_force, _profile, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_destroy_project)

    c = sub.add_parser(
        "destroy-instance", help="remove the local suite run pointer (not its domains)"
    )
    _suite_run(c)
    _common(c)
    c.set_defaults(func=project.cmd_destroy_instance)

    c = sub.add_parser(
        "run-triggers",
        help="fire the suite run's triggers on the project, nothing else",
    )
    c.add_argument("--project", required=True)
    c.add_argument(
        "--monitor",
        action="store_true",
        help="after triggering, watch the transactions until they finish (needs --time-out)",
    )
    _time_out(c)
    for add in (_profile, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_run_triggers)

    c = sub.add_parser(
        "monitor-project", help="watch a project's transactions until they finish"
    )
    c.add_argument("--project", required=True)
    _time_out(c, required=True)
    for add in (_profile, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=project.cmd_monitor_project)

    c = sub.add_parser(
        "run-actions",
        help="run the suite run's actions stages, in order, as one script -- and nothing else",
    )
    _suite_run(c)
    c.add_argument(
        "--project",
        default=None,
        metavar="P",
        help="the project ${xp:project} names (default: <XP_ID>_<suite>)",
    )
    _selection(c, no_actions=False)
    for add in (_secret_env, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=actions.cmd_run_actions)

    c = sub.add_parser(
        "run-suite",
        help="run the suite run's stages in the order the suite lists them: domains, collections, functions, triggers, monitor, actions, sentinel",
    )
    _suite_run(c)
    _project_opt(c)
    _selection(c)
    for add in (_fail_fast, _secret_env, _profile, _latch, _report, _dry_run, _common):
        add(c)
    c.set_defaults(func=cycle.cmd_run_suite)

    for verb, func, what in (
        ("enable-function", project.cmd_enable_function, "enable"),
        ("disable-function", project.cmd_disable_function, "disable"),
    ):
        c = sub.add_parser(
            verb,
            help=f"{what} a function already registered in a project (tdk fn {what})",
        )
        c.add_argument("--project", required=True)
        c.add_argument("--collection", required=True)
        c.add_argument("--function", required=True, help="the function's name")
        for add in (_profile, _dry_run, _common):
            add(c)
        c.set_defaults(func=func)

    c = sub.add_parser(
        "one-shot",
        help="create-instance + run-suite (the suite's stages, in order), then tear down (--keep preserves)",
    )
    _suite(
        c,
        f"{SUITE_HELP}; a comma list of selectors, or ALL (every suite dir), runs one "
        "one-shot per selector, one at a time unless TDD_PARALLELISM is set "
        "(--suite-run and --project are refused then)",
    )
    _suite_run(c, required=False)
    _project_opt(c)
    c.add_argument(
        "--keep",
        action="store_true",
        help="leave the suite run, project and domains set up afterwards",
    )
    _selection(c)
    for add in (_fail_fast, _secret_env, _profile, _latch, _report, _dry_run, _common):
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
        help="group name for the per-lane suite runs (default: an XP_ID; each lane is a suite run with its own, and its project <XP_ID>_<suite>)",
    )
    c.add_argument(
        "--keep",
        action="store_true",
        help="leave every lane's setup afterwards; a bench with a failed lane is kept regardless",
    )
    for add in (_fail_fast, _secret_env, _profile, _latch, _report, _dry_run, _common):
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
