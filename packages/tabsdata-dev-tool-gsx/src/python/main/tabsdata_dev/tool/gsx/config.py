#
# Copyright 2026 Tabsdata Inc.
#

"""``<tdd_dir>/gsx.toml``: the valid labels and reviewers of each repository.

Named after the command, like every command's config (docs/DESIGN.md), and
user state -- `tdd-install` never writes or removes it. Keyed per repository:
labels and collaborators differ per repo, and a flat list would validate one
repo's names against another's.

The file is read with ``tomllib`` and written by hand, whole, so the comments
in it always describe the gsx that wrote them; ``auto-config`` refreshes a
repo's two lists and leaves every ``default_*`` and every other repo alone.
"""

from __future__ import annotations

import datetime
import json
import pathlib
import tomllib

from tabsdata_dev.common.core import datadir
from tabsdata_dev.common.core.errors import ToolError

from .version import VERSION

FILE_NAME = "gsx.toml"


def path() -> pathlib.Path:
    return datadir.tdd_dir() / FILE_NAME


HEADER = """\
#
# Copyright 2026 Tabsdata Inc.
#

# gsx configuration -- {path}
#
# Rewritten whole by `tdd gsx auto-config`, which refreshes the valid
# label/reviewer lists of the current repository and these comments, and
# preserves every `default_*` you set and every other repository's table.
# Delete the file to start over; gsx recreates it on the next run.
#
# The --label/--reviewer options split their value on commas, so a label
# containing one cannot be used from the command line.

# The gsx that last wrote this file. When it differs from the running gsx the
# file is refreshed, so these comments stay true.
version = {version}

# One table per repository, keyed OWNER/NAME -- labels and collaborators
# differ per repository:
#
#   fetched            when auto-config last refreshed the two lists
#   labels             valid label names, from `gh label list`
#   reviewers          valid logins, from collaborators + assignable users
#   default_labels     applied by `submit`/`apply` to PRs that have no label
#                      yet, before any explicit --label: op, so an explicit op
#                      still wins; skip them for one run with --no-defaults
#   default_reviewers  the same, for reviewers
#
# auto-config overwrites `labels`, `reviewers` and `fetched`; the two
# `default_*` keys are yours and are never touched.
"""


def _toml_str(value: str) -> str:
    """A TOML basic string. JSON's escaping is TOML's for everything we write
    (no control characters), and json.dumps is the stdlib's only string
    quoter."""
    return json.dumps(value)


def _toml_list(values: list[str]) -> str:
    return "[" + ", ".join(_toml_str(v) for v in values) + "]"


def empty() -> dict:
    return {"version": VERSION, "repos": {}}


def read() -> dict:
    """The config, or a fresh empty one when the file does not exist yet."""
    file = path()
    if not file.is_file():
        return empty()
    try:
        raw = tomllib.loads(file.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as error:
        raise ToolError(
            f"{file} is not readable: {error}; fix or delete it, then re-run "
            "(gsx recreates it)"
        ) from error
    repos = {}
    for slug, table in (raw.get("repos") or {}).items():
        if not isinstance(table, dict):
            continue
        repos[slug] = {
            "fetched": str(table.get("fetched", "")),
            "labels": [str(v) for v in table.get("labels", [])],
            "reviewers": [str(v) for v in table.get("reviewers", [])],
            "defaults": {
                "labels": [str(v) for v in table.get("default_labels", [])],
                "reviewers": [str(v) for v in table.get("default_reviewers", [])],
            },
        }
    return {"version": str(raw.get("version", "")), "repos": repos}


def render(config: dict) -> str:
    """The whole file as text -- the header's comments plus one table per
    repository, sorted so a rewrite is a readable diff."""
    lines = [HEADER.format(path=path(), version=_toml_str(VERSION))]
    for slug in sorted(config.get("repos", {})):
        entry = config["repos"][slug]
        defaults = entry.get("defaults") or {}
        lines.append(f"\n[repos.{_toml_str(slug)}]")
        lines.append(f"fetched = {_toml_str(entry.get('fetched', ''))}")
        lines.append(f"labels = {_toml_list(entry.get('labels', []))}")
        lines.append(f"reviewers = {_toml_list(entry.get('reviewers', []))}")
        lines.append(f"default_labels = {_toml_list(defaults.get('labels', []))}")
        lines.append(f"default_reviewers = {_toml_list(defaults.get('reviewers', []))}")
    return "\n".join(lines) + "\n"


def write(config: dict) -> pathlib.Path:
    file = path()
    try:
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_text(render(config), encoding="utf-8")
    except OSError as error:
        raise ToolError(f"cannot write {file}: {error}") from error
    return file


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
