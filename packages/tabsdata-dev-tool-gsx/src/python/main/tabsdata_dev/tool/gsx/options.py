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
# Besides [options], gsx keeps three tables of its own; they are at the end of
# this file, commented out at their defaults.
"""

#: gsx's own tables, commented at their defaults, written after the options --
#: where uncommenting one is valid TOML and gsx reads it back. Once gsx has
#: written the real tables this is not used again: what the file has wins.
CONFIG_TABLES = """\
# gsx's own tables, at their defaults. Uncomment a header and the lines under
# it to set one -- every line below is valid TOML with the `# ` taken off.
#
# Where `approve` reads an approver's review token: op://VAULT/ITEM/FIELD, the
# field being <login> + the suffix.
# [approver-credentials]
# approve_vault = "dev_ci"
# approve_item = "GitHub"
# approve_pat_suffix = ".review.pat"
#
# A name of your own for someone, usable wherever a --reviewer: or --approvers
# value is; file-wide, because a login is a person rather than one repository's
# property. The alias is resolved before the value is validated. These are the
# shipped ones and work without being uncommented -- write one here to change
# where it points, or to add somebody.
# [reviewer-aliases]
# dimas = "aoinokimi"
# joaquin = "joaquin041"
# tucu = "tucu0"
# daniel = "adaydan-tabsdata"
# arvind = "aptabs"
# shreyas = "shreyasvan001"
# david = "tabsdavid"
#
# One table per repository, WRITTEN AND MAINTAINED BY gsx: `fetched`, `labels`
# and `reviewers` are refreshed on their own whenever what they hold cannot
# answer a --label:/--reviewer:, and an edit to them is overwritten. So is
# `version` on [repo] itself, which is the gsx that last refreshed them. The two
# default_* lists are yours and are never touched -- the labels and reviewers
# submit/apply put on that repository's PRs that have none yet.
# [repo."OWNER/NAME"]
# default_labels = []
# default_reviewers = []
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
        "--version", "-V", action="store_true", help="show the version and exit"
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
            "--override",
            "-o",
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
            "--verbose",
            "-v",
            action="store_true",
            default=argparse.SUPPRESS,
            help="show debug events too",
        )
        return sub

    def text_opts(sub: argparse.ArgumentParser, required: str) -> None:
        sub.add_argument(
            "--summary",
            "-s",
            metavar="TEXT",
            help=f"the issue title and the commit subject{required}",
        )
        sub.add_argument(
            "--message",
            "-m",
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
        "check out a stack branch by name, or a pull request by #number",
        "examples:\n"
        "  tdd gsx checkout GCS-15      the branch of that name\n"
        "  tdd gsx checkout '#42'       pull request 42 (quote it: # starts a\n"
        "                               comment in most shells)\n"
        "  tdd gsx checkout             gh's interactive picker\n\n"
        "those two shapes and no others. `gh stack checkout` also takes a bare\n"
        "number and a PR URL, but it resolves a bare number as a stack number\n"
        "first, then a PR, then a branch -- so `42` means whichever exists at\n"
        "the time. A number here says what it counts or is refused.\n\n",
    )
    checkout.add_argument(
        "target",
        nargs="?",
        metavar="BRANCH|#PR",
        help="a branch name, or #N for pull request N; omitted opens gh's picker",
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
        "--move",
        action="store_true",
        help="publish a local `gsx move` too: dissolve the stacks it took apart "
        "on GitHub and relink their PRs (the one step that cannot be undone)",
    )
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

    approve = add(
        "approve",
        "approve PRs as one or more people, each with their own review token",
        "example:\n  tdd gsx approve --approvers dimas,tucu --down-stack\n\n"
        "an approver is impersonated with the review token 1Password holds for\n"
        "their GitHub username ([approver-credentials] in the config); a PR\n"
        "they wrote\n"
        "is skipped, since GitHub refuses a self-approval. A [reviewer-aliases]\n"
        'name is resolved first, so with `dimas = "aoinokimi"`, `--approvers\n'
        "dimas` reads the token `aoinokimi.review.pat`.\n\n",
    )
    approve.add_argument(
        "--approvers",
        "-a",
        action="append",
        default=[],
        metavar="NAME[,NAME...]",
        help="who to approve as; repeatable, and comma separated (required)",
    )
    approve.add_argument(
        "--pr",
        "-p",
        action="append",
        default=[],
        metavar="N[,N...]",
        help="the PRs to approve, by number; repeatable, and comma separated",
    )
    approve.add_argument(
        "--down-stack",
        action="store_true",
        help="the current PR and the ones it sits on, down to main -- what has to be approved for it to merge",
    )
    approve.add_argument(
        "--stack", action="store_true", help="every PR of the current stack"
    )

    purge = add(
        "purge",
        "delete the local branches whose PR is merged or closed on GitHub",
        "example:\n  tdd gsx purge --dry-run\n\n"
        "every local branch is a PR gh can be asked about, so GitHub decides:\n"
        "a branch whose newest PR is MERGED or CLOSED is deleted, one with any\n"
        "OPEN PR is kept, and one with no PR at all is left alone. The trunk,\n"
        "main, master and the branch you are standing on are never deleted.\n"
        "The delete is `git branch -D`, since a squash-merged branch is not an\n"
        "ancestor of the trunk and -d would refuse it -- so run --dry-run first\n"
        "to see the list.\n\n",
    )
    purge.add_argument(
        "--merged-only",
        action="store_true",
        help="delete only merged branches, keeping the ones whose PR was closed unmerged",
    )
    purge.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the `git fetch --prune` first; the PR states are read live either way",
    )

    move = add(
        "move",
        "move the branch you are on, and everything above it, to another stack",
        "examples:\n"
        "  tdd gsx move --to '#41'    onto the top of stack 41\n"
        "  tdd gsx move --to FOO-12   onto that branch, which must be a stack's top\n"
        "  tdd gsx move --to main     onto the trunk, as a stack of its own\n\n"
        "you move OUT of the stack you are standing in: the branch you are on and\n"
        "every branch above it. --to says where to, and takes a stack by #number,\n"
        "the top branch of a stack, a branch whose PR is in no stack (the two\n"
        "become one stack), or the trunk. A stack that is not tracked here is a\n"
        "`gh stack checkout` away and says so; a branch that is not the top of its\n"
        "stack is refused, since the moved branches go above it.\n\n"
        "nothing here reaches GitHub. It forgets both stacks locally, tracks the\n"
        "new arrangement, replays the branch whose parent changed and hands the\n"
        "ones above it to `gh stack rebase --upstack` -- only what moved is\n"
        "rewritten. A conflict stops the replay: resolve it, `git add` (or commit)\n"
        "the files, then `--continue` to finish or `--abort` to put every branch\n"
        "and both stacks back. The move in flight lives in <git-dir>/gsx-move, and\n"
        "while it is there a second move is refused.\n\n"
        "`gsx submit --move` is what publishes it, and that is the irreversible\n"
        "step: the old stack has to be dissolved on GitHub before its PRs can join\n"
        "the new one. Until then `gsx stack` says a move is in progress and `gsx\n"
        "submit` refuses without --move.\n\n",
    )
    move.add_argument(
        "--to",
        metavar="#STACK|BRANCH",
        help="where to: #N for a stack, a stack's top branch, or the trunk",
    )
    move.add_argument(
        "--continue",
        dest="resume",
        action="store_true",
        help="finish a move whose replay stopped on a conflict you have resolved",
    )
    move.add_argument(
        "--abort",
        action="store_true",
        help="undo the move in progress: every branch and both stacks as they were",
    )
    move.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="do not ask; without it the plan is shown and a confirmation is read from the terminal",
    )

    stack = add(
        "stack",
        "the stacks: what this checkout tracks, what only GitHub has, and where "
        "each branch stands",
        "examples:\n"
        "  tdd gsx stack\n"
        "    [#34]  main\n"
        "           =a1        #21  the loader\n"
        "          +[a2]       #22  wire it up\n"
        "           ?a3        #29  one someone else added\n"
        "  tdd gsx stack --short\n"
        "    [#34]  main <- =a1 <-+[a2] <- ?a3\n"
        "  tdd gsx stack -as        (--all --short)\n"
        "    3 stack(s):\n"
        "    [#34]  main <- =a1  <-+[a2]\n"
        "     #40   main <- -b24 <- xb25\n"
        "    ?#41   main <- ?c1\n\n"
        "the stacks come from gh-stack's own state file AND from GitHub's own\n"
        "listing, so what only GitHub has -- a PR someone added to your stack, a\n"
        "stack you have never checked out -- is shown too, as a magenta ?name.\n"
        "White [brackets] mark the stack holding the branch you are on -- the one\n"
        "submit and apply act on -- and that branch, round the name alone.\n"
        "`#-` is a stack that has never been submitted, so it has no number yet.\n\n"
        "each branch also carries how it stands against the remote, which is\n"
        "fetched first so the symbols mean what they say. --local and --remote\n"
        "show one side each and carry no such symbols: there is nothing to\n"
        "compare against. The gh-stack extension is never needed.\n\n",
    )
    stack.add_argument(
        "--all",
        "-a",
        action="store_true",
        help="every stack, not just the one you are on",
    )
    stack.add_argument(
        "--short",
        "-s",
        action="store_true",
        help="one line per stack instead of one per PR; asks gh for no PR titles",
    )
    stack.add_argument(
        "--remote",
        "-r",
        action="store_true",
        help="GitHub's stacks only: what it has, with nothing compared against it",
    )
    stack.add_argument(
        "--local",
        "-l",
        action="store_true",
        help="the stacks tracked here only: no gh, no network, nothing compared",
    )
    stack.add_argument(
        "--merged",
        action="store_true",
        help="show the merged and closed PRs too; a stack's finished PRs are left out",
    )
    stack.add_argument(
        "--no-fetch",
        action="store_true",
        help="skip the fetch; the sync symbols are then as of the last one, and say so",
    )


def doc() -> config_mod.Doc:
    """The default document: gsx's own options, as its parser declares them."""
    parser = cli.parser(NAME, DESCRIPTION)
    configure(parser)
    return config_mod.from_parser(NAME, parser, CONFIG_PREAMBLE)
