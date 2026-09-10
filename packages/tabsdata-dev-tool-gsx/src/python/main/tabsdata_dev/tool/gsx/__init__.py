#
# Copyright 2026 Tabsdata Inc.
#

"""gsx -- GitHub issues + `gh stack`, the way gtx does Jira + Graphite.

One command turns pending changes into a GitHub issue, a stack branch and a
commit; another pushes the stack, opens its PRs and labels them. For a
repository that uses neither Jira nor Graphite.

    tdd gsx create   -s SUMMARY [-m BODY] [--i:FLAG] [--s:FLAG] [-- PATH...]
    tdd gsx update   [-s SUMMARY] [-m BODY] [--i:FLAG] [--e:FLAG]
    tdd gsx checkout [BRANCH|#PR] [--c:FLAG]
    tdd gsx submit   [--label:S[:M] LIST]... [--reviewer:S[:M] LIST]...
                     [--sync] [--move] [--draft] [--no-defaults] [--p:|--s:|--e:FLAG]
    tdd gsx apply    [--label:S[:M] LIST]... [--reviewer:S[:M] LIST]...
                     [--no-defaults] [--e:FLAG]
    tdd gsx purge    [--merged-only] [--no-fetch] [--dry-run]
    tdd gsx move     --to #STACK|BRANCH | --continue | --abort  [--yes] [--dry-run]
    tdd gsx stack    [--all|-a] [--short|-s] [--remote|-r|--local|-l] [--no-fetch]

Branch and commit are named from the repository: `tabsdata-conn-gcs` issue 15
-> branch `GCS-15`, commit `[GCS-15] <summary>`, trailer `Closes #15`. The
valid labels and reviewers of each repository live in `<tdd_dir>/gsx.toml`,
which gsx refreshes on its own when what it holds cannot answer a value.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import cli, render
from tabsdata_dev.common.core.errors import ToolError

from . import args as args_mod
from . import commands, gh
from . import move as move_mod
from .args import NATIVES, TAKES_LR
from .options import DESCRIPTION, NAME, CONFIG_PREAMBLE, CONFIG_TABLES, configure

HANDLERS = {
    "create": commands.create,
    "update": commands.update,
    "checkout": commands.checkout,
    "submit": commands.submit,
    "apply": commands.apply,
    "approve": commands.approve,
    "purge": commands.purge,
    "move": commands.move,
    "stack": commands.stack,
}


def _body(parsed_args, out: render.Renderer, extras: args_mod.Extras) -> int:
    if getattr(parsed_args, "version", False):
        from .version import VERSION

        return out.ok(f"gsx {VERSION}", version=VERSION)
    subcommand = getattr(parsed_args, "subcommand", None)
    if not subcommand:
        raise ToolError(
            "a subcommand is required: " + ", ".join(HANDLERS) + " (see --help)"
        )
    natives = NATIVES[subcommand]
    args_mod.check_overlaps(extras, natives, parsed_args.override, out)
    runner = gh.Runner(out=out, dry_run=parsed_args.dry_run)
    _say_if_moving(runner, out, subcommand)
    message, fields = HANDLERS[subcommand](parsed_args, out, runner, extras)
    return out.ok(message, gsx=subcommand, dry_run=parsed_args.dry_run, **fields)


def _say_if_moving(runner: gh.Runner, out: render.Renderer, subcommand: str) -> None:
    """Every command says when a move is unfinished, before it does anything.

    A move is in progress from the first `gsx move` until `gsx submit --move`
    publishes it, and in that window every branch this repository has may be
    somewhere the operator did not put it and GitHub does not know about. That
    is worth knowing whichever command was reached for, so it is said here
    rather than in each of them -- one wording, and no command that can forget.

    `move` is the exception: it refuses outright (`--to`) or acts on the
    session (`--continue`, `--abort`), and both messages say more than this
    one. Anything that cannot answer -- not a git repository, no git at all --
    is not an error of the command that was asked for.
    """
    if subcommand == "move":
        return
    try:
        session = move_mod.load(runner)
    except (ToolError, OSError):
        return
    if session is not None:
        out.warn(session.line())


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    # gsx's own two grammars leave argv before argparse sees it: which
    # subcommand they belong to is the first bare word.
    subcommand = next((token for token in raw if not token.startswith("-")), None)
    if subcommand in NATIVES:
        try:
            rest, extras = args_mod.split(
                raw, NATIVES[subcommand], subcommand in TAKES_LR
            )
        except Exception as error:  # noqa: BLE001 -- rendered by run(), below
            out = render.Renderer(NAME)
            return out.error(str(error))
    else:
        rest, extras = raw, args_mod.Extras()
    return cli.run(
        NAME,
        DESCRIPTION,
        lambda parsed, out: _body(parsed, out, extras),
        argv=rest,
        configure=configure,
        config_preamble=CONFIG_PREAMBLE,
        config_tables=CONFIG_TABLES,
    )


if __name__ == "__main__":
    sys.exit(main())
