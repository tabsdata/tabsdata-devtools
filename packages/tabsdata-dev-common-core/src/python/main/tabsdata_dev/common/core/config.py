#
# Copyright 2026 Tabsdata Inc.
#

"""``<tdd_dir>/<command>.toml``: a command's config, and its default options.

Every command keeps one file, named after itself, holding two kinds of thing:

* ``[options]`` -- what its options default to, merged into the command line
  before the command runs (``[options.<action>]`` for one action only); typed
  options always win. This is the same job the old ``default-opts/*.txt``
  files did, in the command's own file.
* whatever else the command needs to remember (``gsx`` keeps a table per
  repository), written by the command itself.

The document is derived from the command's argparse parser, so the tables it
offers can never drift from the options themselves -- but it lists **no
options**: only the `[options]` and `[options.<action>]` headers, plus whatever
the file already sets. Listing every option at its built-in value would put a
copy of today's defaults in the reader's file, where a later change to one of
them would never reach them; and it is not needed for discovery, since
`config --show` prints every option with its default and marks the ones this
file sets.

Writes go through a temporary file in the same directory and one ``os.replace``
-- an interrupted write leaves the previous file, never half a file.
"""

from __future__ import annotations

import argparse
import contextlib
import os
import pathlib
import tempfile
import tomllib
from dataclasses import dataclass, field
from typing import Any

from . import datadir, render
from .errors import ToolError

# The options every command gets from the shared layer; they belong in the file
# like any other, so they are not special-cased away.
OPTIONS_TABLE = "options"
HIGHLIGHT = "36"  # cyan: a value the file sets, next to the defaults around it


def path(command: str) -> pathlib.Path:
    return datadir.tdd_dir() / f"{command}.toml"


# --------------------------------------------------------------- the values
def toml_value(value: Any) -> str:
    """A TOML scalar or array. Only what an option default can be."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return repr(value)
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(toml_value(v) for v in value) + "]"
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    return f'"{text}"'


def to_argv(name: str, value: Any) -> list[str]:
    """The tokens a configured default contributes to a command line.

    A flag is its presence (``true`` -> ``--flag``, ``false`` -> nothing: a
    store_true option cannot be turned off from a command line either), a list
    repeats the option, everything else is ``--name value``.
    """
    option = f"--{name.replace('_', '-')}"
    if isinstance(value, bool):
        return [option] if value else []
    if isinstance(value, (list, tuple)):
        return [token for item in value for token in (option, str(item))]
    return [option, str(value)]


# ------------------------------------------------------------ the defaults
@dataclass
class Doc:
    """A command's default document: the options it has, per action."""

    command: str
    # action ("" for the command itself) -> option name -> (default, help)
    actions: dict[str, dict[str, tuple[Any, str]]] = field(default_factory=dict)
    preamble: str = ""
    #: The tables the command keeps of its own, at their defaults, commented
    #: out -- written at the END of the document, where uncommenting one is
    #: valid TOML and survives every later rewrite. Used only while the file
    #: has none of its own; once the command has written real ones, those are
    #: what a rewrite carries across.
    tables: str = ""

    def defaults(self) -> dict[str, dict[str, Any]]:
        return {
            action: {name: value for name, (value, _) in options.items()}
            for action, options in self.actions.items()
        }


_SKIP_ACTIONS = {"help", "version"}


def from_parser(
    command: str,
    parser: argparse.ArgumentParser,
    preamble: str = "",
    tables: str = "",
) -> Doc:
    """Read the command's own parser: every option that HAS a default.

    An option with no default (a required value, a path to act on) is left out
    -- there is nothing to put in the file and a blank one would be merged in
    as an empty value.
    """
    doc = Doc(command=command, preamble=preamble, tables=tables)
    doc.actions[""] = _options_of(parser)
    for action in parser._actions:  # noqa: SLF001 -- argparse exposes no other way
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            for name, sub in action.choices.items():
                found = _options_of(sub)
                if found:
                    doc.actions[name] = found
    return doc


def _options_of(parser: argparse.ArgumentParser) -> dict[str, tuple[Any, str]]:
    found: dict[str, tuple[Any, str]] = {}
    for action in parser._actions:  # noqa: SLF001
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            continue
        if not action.option_strings or action.dest in ("help", argparse.SUPPRESS):
            continue
        if action.dest in _SKIP_ACTIONS or action.default in (None, argparse.SUPPRESS):
            continue
        found[action.dest] = (action.default, (action.help or "").strip())
    return found


# ------------------------------------------------------------- the file
HEADER = """\
#
# Copyright 2026 Tabsdata Inc.
#
"""

#: The only thing the document explains. The options themselves are not listed:
#: `config --show` prints every one with its default and marks what this file
#: sets, which is a better answer than a wall of commented lines that go stale
#: in the reader's copy the moment a default changes.
OPTIONS_NOTE = """\
# Each subcommand may have an [options.<SUBCOMMAND>] table setting user
# defaults: key is the option, value is its value, strings in double quotes.
"""


def render_doc(doc: Doc, values: dict[str, dict[str, Any]] | None = None) -> str:
    """The file's text: the `[options]` tables, holding only what `values` says
    is actually set. No option is written at its built-in default."""
    values = values or {}
    lines = [HEADER]
    if doc.preamble:
        # The trailing newline is the blank line before the note: the join adds
        # one of its own, and a preamble butting against it reads as one block.
        lines.append(doc.preamble.rstrip("\n") + "\n")
    lines.append(OPTIONS_NOTE.rstrip("\n"))
    for action in sorted(doc.actions, key=lambda a: (a != "", a)):
        options = doc.actions[action]
        if not options:
            continue
        table = OPTIONS_TABLE if action == "" else f"{OPTIONS_TABLE}.{action}"
        lines.append(f"\n[{table}]")
        # Only what the file actually sets. An empty table is the normal state
        # and is left in place: it says which subcommands take defaults at all.
        for name, (_default, _help) in sorted(options.items()):
            set_to = values.get(action, {}).get(name)
            if set_to is not None:
                lines.append(f"{name} = {toml_value(set_to)}")
    return "\n".join(lines) + "\n"


def document(doc: Doc, values: dict[str, dict[str, Any]] | None = None) -> str:
    """The whole file: the option tables, then whatever tables belong after them
    -- the command's real ones when the file has them, else its commented
    defaults, so a reader can see they exist at all."""
    tail = kept_tables(doc.command) or doc.tables.strip("\n")
    return render_doc(doc, values) + (f"\n{tail}\n" if tail else "")


def read(command: str) -> dict[str, Any]:
    """The whole file as a dict, or ``{}`` when there is none."""
    file = path(command)
    if not file.is_file():
        return {}
    try:
        return tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ToolError(
            f"{file} is not readable: {error}; fix it, or move it aside and "
            f"run `tdd {command} config --create`"
        ) from error


def options_in(command: str) -> dict[str, dict[str, Any]]:
    """The ``[options]`` tables: action ("" for the command) -> name -> value."""
    table = read(command).get(OPTIONS_TABLE) or {}
    found: dict[str, dict[str, Any]] = {"": {}}
    for key, value in table.items():
        if isinstance(value, dict):
            found[key] = dict(value)
        else:
            found[""][key] = value
    return found


def write(command: str, text: str) -> pathlib.Path:
    """Write the file whole, atomically: a temporary file in the same directory
    and one rename, so an interrupted write cannot leave half a config."""
    file = path(command)
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        handle = tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=file.parent,
            prefix=f".{file.name}.",
            suffix=".tmp",
            delete=False,
        )
        temporary = pathlib.Path(handle.name)
        try:
            with handle:
                handle.write(text)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, file)
        except BaseException:
            with contextlib.suppress(OSError):
                temporary.unlink()
            raise
    except OSError as error:
        raise ToolError(f"cannot write {file}: {error}") from error
    return file


def kept_tables(command: str) -> str:
    """The file's tables that are not ``[options]``, verbatim.

    What the command keeps of its own is text this module never generated, so
    a rewrite of the option template carries it across unparsed rather than
    round-tripping it through a TOML writer that would drop its comments.
    """
    file = path(command)
    if not file.is_file():
        return ""
    kept: list[str] = []
    keeping = False
    for line in file.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("[") and stripped.endswith("]"):
            name = stripped[1:-1].strip()
            keeping = name != OPTIONS_TABLE and not name.startswith(f"{OPTIONS_TABLE}.")
        if keeping:
            kept.append(line)
    return "\n".join(kept).strip("\n")


def update(
    command: str,
    doc: Doc,
    values: dict[str, dict[str, Any]] | None = None,
    keep: str | None = None,
) -> pathlib.Path:
    """Rewrite the file whole: the option template with `values` filled in,
    then what the command keeps of its own (`keep`, already TOML; by default
    whatever the file has now)."""
    values = options_in(command) if values is None else values
    tail = kept_tables(command) if keep is None else keep.strip("\n")
    tail = tail or doc.tables.strip("\n")
    return write(command, render_doc(doc, values) + (f"\n{tail}\n" if tail else ""))


# -------------------------------------------------------------- the action
def _highlight(text: str, stream) -> str:
    if os.environ.get("NO_COLOR") or not render._isatty(stream):  # noqa: SLF001
        return text
    return f"\033[{HIGHLIGHT}m{text}{render.RESET}"


def _table_lines(data: dict[str, Any], prefix: str = "") -> list[str]:
    """A table dict as `[name]` headers and `key = value` lines, sub-tables and
    all -- `{"repo": {"o/n": {...}}}` is `[repo."o/n"]`. Scalars come first, so
    a table's own keys are not buried under its children."""
    lines: list[str] = []
    scalars = {k: v for k, v in data.items() if not isinstance(v, dict)}
    tables = {k: v for k, v in data.items() if isinstance(v, dict)}
    if scalars or (not tables and prefix):
        lines.append(f"\n[{prefix}]" if prefix else "")
        for key, value in scalars.items():
            lines.append(f"  {key} = {toml_value(value)}")
    for name, table in tables.items():
        # A key that is not bare has to be quoted, the way it is in the file.
        part = name if name.replace("_", "").replace("-", "").isalnum() else f'"{name}"'
        lines.extend(_table_lines(table, f"{prefix}.{part}" if prefix else part))
    return lines


def _default_tables(doc: Doc) -> dict[str, Any]:
    """The command's own tables at their defaults, read back out of the
    commented block it supplies. Best effort: a block that does not uncomment
    into TOML simply has nothing to show."""
    if not doc.tables:
        return {}
    text = "\n".join(
        line[2:] if line.startswith("# ") else line
        for line in doc.tables.splitlines()
        if line.startswith("# [") or " = " in line
    )
    try:
        return tomllib.loads(text)
    except tomllib.TOMLDecodeError:
        return {}


def show(doc: Doc, stream) -> tuple[str, dict[str, Any]]:
    """What the command's options resolve to now, with the values this file
    sets highlighted -- everything else is the built-in default."""
    file = path(doc.command)
    configured = options_in(doc.command)
    lines = [f"{file}{'' if file.is_file() else '  (no file yet)'}"]
    changed: dict[str, Any] = {}
    for action in sorted(doc.actions, key=lambda a: (a != "", a)):
        options = doc.actions[action]
        if not options:
            continue
        lines.append(f"\n[{OPTIONS_TABLE}{'.' + action if action else ''}]")
        for name, (default, _) in sorted(options.items()):
            set_to = configured.get(action, {}).get(name)
            if set_to is None:
                lines.append(f"  {name} = {toml_value(default)}")
            else:
                key = f"{action}.{name}" if action else name
                changed[key] = set_to
                lines.append(
                    "  "
                    + _highlight(f"{name} = {toml_value(set_to)}", stream)
                    + (
                        f"   (default {toml_value(default)})"
                        if set_to != default
                        else ""
                    )
                )
    # What the command keeps of its own. The file's tables when it has them --
    # that is the real state, the repositories gsx has learnt and so on -- and
    # otherwise the defaults it ships, so the reader sees they exist at all.
    other = {k: v for k, v in read(doc.command).items() if k != OPTIONS_TABLE}
    if other:
        lines.append(f"\nkept by `tdd {doc.command}` itself:")
        lines.extend(_table_lines(other))
    elif _default_tables(doc):
        lines.append(
            f"\nkept by `tdd {doc.command}` itself (defaults; not set here yet):"
        )
        lines.extend(_table_lines(_default_tables(doc)))
    return ("\n".join(lines), changed)


SUMMARY = "this command's config file: --show, --default, --create [--force]"


def announce(parser: argparse.ArgumentParser, command: str) -> None:
    """Make `config` visible in the command's own --help.

    The action is served before the parser ever sees it, so it would otherwise
    be a word nobody could discover: registered here as a subcommand where the
    command has them, and named in the epilog where it does not.
    """
    for action in parser._actions:  # noqa: SLF001 -- argparse exposes no other way
        if isinstance(action, argparse._SubParsersAction):  # noqa: SLF001
            if OPTIONS_TABLE not in action.choices and "config" not in action.choices:
                action.add_parser("config", help=SUMMARY, description=SUMMARY)
            return
    line = f"config: {SUMMARY} (tdd {command} config --help)"
    parser.epilog = f"{parser.epilog}\n\n{line}" if parser.epilog else line
    parser.formatter_class = argparse.RawDescriptionHelpFormatter


def run_action(doc: Doc, argv: list[str], out: render.Renderer) -> int:
    """`tdd <command> config [--show|--default|--create [--force]]`.

    Every command has it, from the shared layer; see docs/command-cli-guidelines.md.
    """
    parser = argparse.ArgumentParser(
        prog=f"tdd {doc.command} config",
        description=f"the config file of `tdd {doc.command}`: {path(doc.command)}",
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--show",
        action="store_true",
        help="what the options resolve to now; what this file sets is highlighted (default)",
    )
    group.add_argument(
        "--default",
        action="store_true",
        help="print the default config, the document --create would write",
    )
    group.add_argument(
        "--create",
        action="store_true",
        help="write the default config; refuses when the file exists",
    )
    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="--create: overwrite an existing file",
    )
    parser.add_argument(
        "--format",
        choices=("json", "view"),
        default=argparse.SUPPRESS,
        help="json is JSON Lines, one event per line (default: view)",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show debug events too",
    )
    try:
        args = parser.parse_args(argv)
    except SystemExit as exit_:  # --help, or argparse's own usage error
        if exit_.code in (0, None):
            return 0
        raise ToolError(
            f"config: bad arguments (see `tdd {doc.command} config --help`)"
        ) from exit_

    file = path(doc.command)
    if args.default:
        return out.ok(document(doc), config=str(file), action="default")
    if args.create:
        if file.is_file() and not args.force:
            raise ToolError(f"{file} already exists; --force overwrites it")
        # --force rewrites the option template and carries across both what the
        # file set and what the command keeps of its own.
        existed = file.is_file()
        update(doc.command, doc)
        return out.ok(
            f"wrote {file}", config=str(file), action="create", replaced=existed
        )
    message, changed = show(doc, out.out)
    return out.ok(message, config=str(file), action="show", changed=changed)
