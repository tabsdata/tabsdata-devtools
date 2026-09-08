#
# Copyright 2026 Tabsdata Inc.
#

"""Per-command default options, read from the command's own config file.

    <tdd_dir>/<command>.toml

        [options]              every action of <command>
        [options.<action>]     that action only

The `tdd` shell function asks this module to merge them into the command line
before dispatching, so both halves get defaults without knowing about them, and
prints the resolved invocation.

Precedence: what was typed wins over any default, and an action's table wins
over the command's. An option counts as typed when its name appears on the
command line in either spelling (`--name` or `--name=`); the default is then
left out entirely, never appended as a second value. The two short forms the
guidelines allow are understood as their long names.

The mapping from a TOML value to command-line tokens is the twin of
`common.core.config.to_argv` -- this package has no dependencies, not even on
common-core, and a test keeps the two honest.
"""

from __future__ import annotations

import pathlib
import tomllib
from typing import Any

OPTIONS_TABLE = "options"
# The short forms the guidelines allow, so a typed `-f` overrides a preset `--force`.
ALIASES = {
    "-v": "--verbose",
    "-h": "--help",
    "-f": "--force",
    "-y": "--yes",
    "-V": "--version",
}


class DefaultsError(Exception):
    pass


def config_path(dir_: pathlib.Path, command: str) -> pathlib.Path:
    return dir_ / f"{command}.toml"


def to_argv(name: str, value: Any) -> list[str]:
    """The tokens a configured default contributes. Twin of
    `common.core.config.to_argv` -- an empty string contributes nothing, so a
    line copied out of `config --show` for an option with no built-in default
    leaves that option alone instead of passing it an empty argument."""
    option = f"--{name.replace('_', '-')}"
    if isinstance(value, bool):
        return [option] if value else []
    if value == "":
        return []
    if isinstance(value, (list, tuple)):
        return [token for item in value for token in (option, str(item))]
    return [option, str(value)]


def option_name(token: str) -> str:
    return ALIASES.get(token, token.split("=", 1)[0])


def typed_names(argv: list[str]) -> set[str]:
    return {option_name(a) for a in argv if a.startswith("-") and a != "-"}


def read(dir_: pathlib.Path, command: str) -> dict[str, dict[str, Any]]:
    """The `[options]` tables: action ("" for the command) -> name -> value."""
    path = config_path(dir_, command)
    if not path.is_file():
        return {}
    try:
        document = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise DefaultsError(f"{path}: {error}") from error
    table = document.get(OPTIONS_TABLE)
    if table is None:
        return {}
    if not isinstance(table, dict):
        raise DefaultsError(f"{path}: [{OPTIONS_TABLE}] must be a table")
    found: dict[str, dict[str, Any]] = {"": {}}
    for key, value in table.items():
        if isinstance(value, dict):
            found[key] = dict(value)
        else:
            found[""][key] = value
    return {action: values for action, values in found.items() if values}


def resolve(
    dir_: pathlib.Path, command: str, argv: list[str]
) -> tuple[list[str], list[str]] | None:
    """The merged command line and the tables used, or None when none apply."""
    tables = read(dir_, command)
    if not tables:
        return None
    action = argv[0] if argv and not argv[0].startswith("-") else ""
    # Most specific first, so its names are "present" by the time the general
    # table is applied and cannot be overridden by it.
    order = [a for a in (action, "") if a in tables]
    if not order:
        return None
    merged = list(argv)
    present = typed_names(argv)
    used: list[str] = []
    name_of = config_path(dir_, command).name
    for table in order:
        applied = False
        for key, value in tables[table].items():
            name = f"--{key.replace('_', '-')}"
            if name in present:
                continue
            tokens = to_argv(key, value)
            present.add(name)
            if tokens:
                merged.extend(tokens)
                applied = True
        if applied:
            used.append(f"{name_of} [{OPTIONS_TABLE}{'.' + table if table else ''}]")
    if merged == argv:
        return None
    return merged, used
