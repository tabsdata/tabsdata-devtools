#
# Copyright 2026 Tabsdata Inc.
#

"""gsx -- GitHub issues + `gh stack`, the way gtx does Jira + Graphite.

One command turns pending changes into a GitHub issue, a stack branch and a
commit; another pushes the stack, opens its PRs and labels them. For a
repository that uses neither Jira nor Graphite.

    tdd gsx create   -s SUMMARY [-m BODY] [--i:FLAG] [--s:FLAG] [-- PATH...]
    tdd gsx update   [-s SUMMARY] [-m BODY] [--i:FLAG] [--e:FLAG]
    tdd gsx checkout [BRANCH|PR|URL|N] [--c:FLAG]
    tdd gsx submit   [--label:S[:M] LIST]... [--reviewer:S[:M] LIST]...
                     [--sync] [--draft] [--no-defaults] [--p:|--s:|--e:FLAG]
    tdd gsx apply    [--label:S[:M] LIST]... [--reviewer:S[:M] LIST]...
                     [--no-defaults] [--e:FLAG]

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
from .args import NATIVES, TAKES_LR
from .options import DESCRIPTION, NAME, CONFIG_PREAMBLE, configure

HANDLERS = {
    "create": commands.create,
    "update": commands.update,
    "checkout": commands.checkout,
    "submit": commands.submit,
    "apply": commands.apply,
    "approve": commands.approve,
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
    message, fields = HANDLERS[subcommand](parsed_args, out, runner, extras)
    return out.ok(message, gsx=subcommand, dry_run=parsed_args.dry_run, **fields)


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
    )


if __name__ == "__main__":
    sys.exit(main())
