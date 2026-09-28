#
# Copyright 2026 Tabsdata Inc.
#

"""The outer shape every Python command shares -- docs/command-cli-guidelines.md.

`parser()` gives an argparse parser that already has the mandatory options;
`run()` wraps a command's body so that argument errors, exceptions and return
codes all come out as the guidelines require: one ok or error event, exit 0 or
1, and a failure log on the way out. A command writes only its own logic:

    def body(args, out):            # out is a render.Renderer
        out.debug("starting")
        return out.ok("done", count=3)

    def main() -> int:
        return cli.run("audit", "audit dependency pins", body)
"""

from __future__ import annotations

import argparse
import sys
import traceback
from collections.abc import Callable

from . import config, errors, render


class ColorHelp(argparse.RawDescriptionHelpFormatter):
    """argparse's layout, then its headings and terms coloured.

    Colour is applied to the finished text rather than to each piece, so it
    cannot disturb a column: argparse counts characters, and an escape has
    none to spare. RawDescription keeps a hand-written epilog as written.
    """

    def format_help(self) -> str:
        return render.colorize_help(super().format_help(), sys.stdout)


def _colorize(parser: argparse.ArgumentParser) -> None:
    """Give a parser and every subparser under it the coloured formatter."""
    parser.formatter_class = ColorHelp
    for action in parser._actions:  # noqa: SLF001 -- argparse exposes no other way
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for sub in action.choices.values():
                _colorize(sub)


class _Parser(argparse.ArgumentParser):
    """argparse exits 2 on a bad argument; the guidelines allow only 1, and
    want the failure rendered like any other error."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


class UsageError(Exception):
    pass


def parser(
    prog: str,
    description: str,
    formats: dict[str, str] | None = None,
    default_format: str = "view",
) -> argparse.ArgumentParser:
    """The command's parser, named the way the command is run.

    `tdd <tool>`, not `<tool>`: argparse would otherwise put the bare executable
    in every usage line and every subcommand's, which is a command nobody types
    -- the tools live inside a toolset venv and the front door is `tdd`. The
    shell half has always written its usage that way, so this is also what makes
    the two halves' help read alike."""
    # add_help=False so the help flag is ours to declare: argparse's own is
    # `-h, --help`, and every option here reads long form first.
    p = _Parser(prog=f"tdd {prog}", description=description, add_help=False)
    p.add_argument(
        "--help", "-h", action="help", help="show this help message and exit"
    )
    p.add_argument("--verbose", "-v", action="store_true", help="show debug events too")
    formats = formats or {}
    extra = "".join(f"; {name}: {what}" for name, what in formats.items())
    p.add_argument(
        "--format",
        choices=(*formats, "json", "view"),
        default=default_format,
        help=f"json is JSON Lines, one event per line{extra} (default: {default_format})",
    )
    return p


def confirm(out: render.Renderer, prompt: str, *, assume_yes: bool) -> None:
    """Stop unless the operator said yes -- on the command line, or at the
    keyboard. Never inferred from the absence of an answer.

    For the commands whose work is worth a second thought. `--yes`/`-y` is the
    flag the guidelines reserve for it. json is refused outright even on a
    terminal: a machine reading JSON Lines is not there to answer. The prompt
    is the one thing a command puts on the terminal that is not an event -- it
    is a question, so it goes to stderr and stays out of the stream.
    """
    if assume_yes:
        return
    if out.fmt == "json" or not sys.stdin.isatty():
        raise errors.ToolError(
            f"{prompt} -- pass --yes to proceed (no terminal to ask on)"
        )
    print(f"\n{prompt} [y/N] ", end="", file=sys.stderr, flush=True)
    if sys.stdin.readline().strip().lower() not in ("y", "yes"):
        raise errors.ToolError("aborted")


def run(
    prog: str,
    description: str,
    body: Callable[[argparse.Namespace, render.Renderer], int | None],
    argv: list[str] | None = None,
    configure: Callable[[argparse.ArgumentParser], None] | None = None,
    config_preamble: str = "",
    config_tables: str = "",
    formats: dict[str, str] | None = None,
    default_format: str = "view",
) -> int:
    """Parse, render, run, and map everything onto exit 0 or 1.

    `configure` adds the command's own options to the parser before parsing.
    The body's return value is the exit code (None counts as 0); anything else
    it raises becomes an error event with the traceback in the log.
    `config_preamble` is TOML the command's own `config --create` template
    carries above the options (what it keeps of its own, explained), and
    `config_tables` the tables it keeps of its own, commented at their
    defaults, written after them -- see `config.Doc.tables`.
    `formats` are `--format` values the command renders itself, beside json
    and view, each with what it is for the help (`_1p fetch`'s export lines):
    the renderer is view for them, so the body's ok still goes to stdout, and
    the body reads `args.format` to shape it. `default_format` may be one of
    them.
    """
    p = parser(prog, description, formats, default_format)
    if configure is not None:
        configure(p)
    raw = list(argv if argv is not None else sys.argv[1:])
    # --format has to be known before an argument error can be rendered, so
    # peek at it the same way the parser would.
    fmt, verbose = _peek_common(raw)
    out = render.Renderer(prog, fmt=fmt, verbose=verbose)
    # `config` is every command's, from here rather than from each parser: the
    # document it reads and writes is derived from the parser above, so it can
    # never drift from the options themselves.
    config.announce(p, prog)
    _colorize(p)
    if raw[:1] == ["config"]:
        try:
            return config.run_action(
                config.from_parser(prog, p, config_preamble, config_tables),
                raw[1:],
                out,
            )
        except errors.ToolError as exc:
            return out.error(str(exc))
    try:
        args = p.parse_args(argv)
    except UsageError as exc:
        return out.error(f"{exc} (see --help)")
    except SystemExit as exc:  # --help
        return 0 if exc.code in (0, None) else 1
    fmt = args.format if args.format in ("json", "view") else "view"
    out = render.Renderer(prog, fmt=fmt, verbose=args.verbose)
    try:
        code = body(args, out)
    except KeyboardInterrupt:
        return out.error("interrupted")
    except SystemExit as exc:
        # A body that calls sys.exit() still gets the 0/1 mapping; a message
        # passed to it is worth an error line.
        if exc.code in (0, None):
            return 0
        return out.error(
            str(exc.code) if not isinstance(exc.code, int) else f"exit {exc.code}"
        )
    except errors.ToolError as exc:
        # The expected, user-facing failure: its message is the whole story on
        # the terminal, so neither the class name nor a traceback belongs in
        # front of it -- but whatever the failing system said goes to the log.
        return out.error(str(exc), details=getattr(exc, "details", ""))
    except Exception as exc:  # noqa: BLE001 -- the guidelines want one error line, not a trace
        return out.error(f"{type(exc).__name__}: {exc}", details=traceback.format_exc())
    return 0 if code in (0, None) else 1


def _peek_common(argv: list[str]) -> tuple[str, bool]:
    fmt, verbose = "view", False
    for i, arg in enumerate(argv):
        if arg in ("-v", "--verbose"):
            verbose = True
        elif (
            arg == "--format" and i + 1 < len(argv) and argv[i + 1] in ("json", "view")
        ):
            fmt = argv[i + 1]
        elif arg.startswith("--format=") and arg[9:] in ("json", "view"):
            fmt = arg[9:]
    return fmt, verbose
