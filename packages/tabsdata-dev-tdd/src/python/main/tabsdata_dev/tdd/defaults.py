#
# Copyright 2026 Tabsdata Inc.
#

"""Per-command default options. Standard library only.

    <tdd_dir>/default-opts/<command>.txt
    <tdd_dir>/default-opts/<command>_<action>.txt      e.g. venv_create.txt

One option per line -- `--name value`, `--name=value` or `--flag` -- with `#`
comments and blank lines ignored. The `tdd` shell function asks this module to
merge a file into the command line before dispatching, so both halves get
defaults without knowing about them, and prints the resolved invocation.

Precedence: what was typed wins over any default, and an action's file wins
over the command's. The separator is `_` because command names themselves use
`-` (tdd-env): `tdd-env_activate.txt` is unambiguous where a hyphen would not be. An option counts as typed when its name appears on the
command line in either spelling (`--name` or `--name=`); the default is then
left out entirely, never appended as a second value. The two short forms the
guidelines allow are understood as their long names.
"""

from __future__ import annotations

import pathlib
import re

DIR_NAME = "default-opts"
# The short forms the guidelines allow, so a typed `-f` overrides a preset `--force`.
ALIASES = {
    "-v": "--verbose",
    "-h": "--help",
    "-f": "--force",
    "-y": "--yes",
    "-V": "--version",
}

# A `#` starts a comment at the start of a line or after whitespace, so a value
# like --tag a#b survives.
_COMMENT = re.compile(r"(^|\s)#.*$")


class DefaultsError(Exception):
    pass


def defaults_dir(dir_: pathlib.Path) -> pathlib.Path:
    return dir_ / DIR_NAME


def parse_file(path: pathlib.Path) -> list[list[str]]:
    """Each entry is the tokens to append: ["--name", "value"] or ["--name=value"]
    or ["--flag"]."""
    entries: list[list[str]] = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = _COMMENT.sub("", raw).strip()
        if not line:
            continue
        if not line.startswith("--"):
            raise DefaultsError(
                f"{path}:{lineno}: expected --option, --option value or "
                f"--option=value, got {line!r}"
            )
        entry = line.split(None, 1)
        # `--python 3.12 --type conda` on one line would silently become one
        # value; the format is one option per line, so say so.
        if len(entry) == 2 and re.search(r"(^|\s)--\S", entry[1]):
            raise DefaultsError(f"{path}:{lineno}: one option per line, got {line!r}")
        entries.append(entry)
    return entries


def option_name(token: str) -> str:
    return ALIASES.get(token, token.split("=", 1)[0])


def typed_names(argv: list[str]) -> set[str]:
    return {option_name(a) for a in argv if a.startswith("-") and a != "-"}


def files_for(dir_: pathlib.Path, command: str, argv: list[str]) -> list[pathlib.Path]:
    """The command's file, then the action's when the first argument is a bare
    word. Only files that exist."""
    candidates = [defaults_dir(dir_) / f"{command}.txt"]
    if argv and not argv[0].startswith("-"):
        candidates.append(defaults_dir(dir_) / f"{command}_{argv[0]}.txt")
    return [f for f in candidates if f.is_file()]


def resolve(
    dir_: pathlib.Path, command: str, argv: list[str]
) -> tuple[list[str], list[str]] | None:
    """The merged command line and the file names used, or None if no file applies."""
    files = files_for(dir_, command, argv)
    if not files:
        return None
    merged = list(argv)
    present = typed_names(argv)
    # Most specific first, so its names are "present" by the time the general
    # file is applied and cannot be overridden by it.
    for path in reversed(files):
        for entry in parse_file(path):
            name = option_name(entry[0])
            if name in present:
                continue
            merged.extend(entry)
            present.add(name)
    return merged, [f.name for f in files]
