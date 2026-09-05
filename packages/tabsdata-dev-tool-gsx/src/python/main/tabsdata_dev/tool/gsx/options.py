#
# Copyright 2026 Tabsdata Inc.
#

"""gsx's parser, apart from the entry point.

`config` builds the same parser to derive the default document (and so the
config file's template) from it, and the entry point cannot import the config
side without a cycle -- so the options live here, where both can reach them.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.core import cli, config as config_mod

from .args import NATIVES

NAME = "gsx"
DESCRIPTION = (
    "GitHub issues + `gh stack`: an issue, a stack branch and a PR in one command"
)

# What gsx keeps of its own in the file, above the options.
CONFIG_PREAMBLE = """\
# What gsx keeps here besides the options: one table per repository, because
# labels and collaborators differ per repository -- a flat list would validate
# one repository's names against another's. `tdd gsx auto-config` writes them.
#
#   [gsx]
#   version            the gsx that last refreshed the tables below
#
#   [reviewer-aliases]
#   <alias> = "<login>"  a name of your own for a reviewer, usable anywhere a
#                      --reviewer: value is; file-wide, because a login is a
#                      person rather than a property of one repository
#
#   [repo."OWNER/NAME"]
#   fetched            when auto-config last refreshed the two lists
#   labels             valid label names, from `gh label list`
#   reviewers          valid logins, from collaborators + assignable users
#   default_labels     applied by `submit`/`apply` to PRs of THIS repository
#                      that have no label yet, before any explicit --label: op,
#                      so an explicit op still wins; --no-defaults skips them
#   default_reviewers  the same, for reviewers
#
# auto-config overwrites `labels`, `reviewers` and `fetched`; the two
# `default_*` keys are yours and are never touched.
"""


LR_EPILOG = """\
labels and reviewers:
  --label:<scope>[:<mode>] LIST     --reviewer:<scope>[:<mode>] LIST
  short --l: --r:   scope new|top|all|mine (n|t|a|m, default new)
                    mode  replace|add      (r|a,     default replace)
  new  PRs with no label / no reviewer yet, judged before anything is written
  top  the PR furthest from the trunk   all  every PR   mine  the ones you authored
  LIST is comma separated; "" removes all. Ops apply in the order given, so a
  later op wins on PRs they share. Values are validated against the config,
  which is refreshed once when one is missing; a bad value writes nothing.
"""


def _passthrough_epilog(subcommand: str) -> str:
    natives = NATIVES[subcommand]
    if not natives:
        return ""
    lines = "\n".join(f"  --{n.char}:FLAG [VALUE]   -> {n.target}" for n in natives)
    return (
        "passing flags through to gh:\n"
        f"{lines}\n"
        "  a one-letter FLAG becomes -f, a longer one --flag; --x:name=value is\n"
        "  unambiguous. A flag gsx derives itself is refused unless --override.\n"
    )


def configure(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-V", "--version", action="store_true", help="show the version and exit"
    )
    subs = parser.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    def add(name: str, help_: str, epilog: str = "") -> argparse.ArgumentParser:
        sub = subs.add_parser(
            name,
            help=help_,
            description=help_,
            epilog=epilog + _passthrough_epilog(name),
            formatter_class=argparse.RawDescriptionHelpFormatter,
        )
        sub.add_argument(
            "-o",
            "--override",
            action="store_true",
            help="let passthrough flags override the ones gsx derives (yours go last)",
        )
        sub.add_argument(
            "--dry-run",
            action="store_true",
            help="print the mutating commands instead of running them; read-only ones still run",
        )
        sub.add_argument(
            "--format",
            choices=("json", "view"),
            default=argparse.SUPPRESS,
            help="json is JSON Lines, one event per line (default: view)",
        )
        sub.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="show debug events too",
        )
        return sub

    def text_opts(sub: argparse.ArgumentParser, required: str) -> None:
        sub.add_argument(
            "-s",
            "--summary",
            metavar="TEXT",
            help=f"the issue title and the commit subject{required}",
        )
        sub.add_argument(
            "-m",
            "--message",
            metavar="TEXT",
            help="the issue body and the commit body; - reads stdin",
        )

    create = add(
        "create",
        "create a GitHub issue, a stack branch and a commit from the pending changes",
        "example:\n  tdd gsx create -s 'Fix the parser' -- src/parser.py\n\n",
    )
    text_opts(create, " (required)")
    create.add_argument(
        "paths",
        nargs="*",
        metavar="PATH",
        help="commit only these paths (after --); default: everything pending",
    )

    update = add(
        "update",
        "reword the issue, the commit and the PR that reads from it",
        "example:\n  tdd gsx update -s 'Fix the parser properly'\n\n",
    )
    text_opts(update, "")

    checkout = add(
        "checkout",
        "check out a stack branch by name, PR number, PR URL or stack number",
        "example:\n  tdd gsx checkout GCS-15\n\n",
    )
    checkout.add_argument(
        "target",
        nargs="?",
        metavar="TARGET",
        help="branch, PR number, PR URL or stack number; omitted opens gh's picker",
    )

    submit = add(
        "submit",
        "push the stack, open or refresh its PRs, then apply label/reviewer ops",
        "example:\n  tdd gsx submit --label:new skip-ci --label:top run-ci\n\n"
        + LR_EPILOG
        + "\n",
    )
    submit.add_argument("--sync", action="store_true", help="`gh stack sync` first")
    submit.add_argument(
        "--draft", action="store_true", help="do not open the PRs in a browser"
    )
    submit.add_argument(
        "--no-defaults",
        action="store_true",
        help="skip the config's default_labels/default_reviewers for this run",
    )

    apply_ = add(
        "apply",
        "set labels and reviewers on the stack's existing PRs; nothing is pushed",
        "example:\n  tdd gsx apply --label:new skip-ci --label:top run-ci\n\n"
        + LR_EPILOG
        + "\n",
    )
    apply_.add_argument(
        "--no-defaults",
        action="store_true",
        help="skip the config's default_labels/default_reviewers for this run",
    )

    add(
        "auto-config",
        "refresh this repository's valid labels and reviewers in <tdd_dir>/gsx.toml",
        "example:\n  tdd gsx auto-config\n\n",
    )


def doc() -> config_mod.Doc:
    """The default document: gsx's own options, as its parser declares them."""
    parser = cli.parser(NAME, DESCRIPTION)
    configure(parser)
    return config_mod.from_parser(NAME, parser, CONFIG_PREAMBLE)
