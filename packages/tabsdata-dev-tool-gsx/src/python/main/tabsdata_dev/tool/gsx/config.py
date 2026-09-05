#
# Copyright 2026 Tabsdata Inc.
#

"""What gsx keeps in ``<tdd_dir>/gsx.toml``: one table per repository.

The file is every command's config file (`common.core.config`): its
``[options]`` table holds what gsx's own options default to, and gsx adds
``[gsx]`` and one ``[repos."OWNER/NAME"]`` table per repository. Labels and
collaborators differ per repository -- a flat list would validate one
repository's names against another's -- and so do the two ``default_*`` lists,
which are the labels and reviewers `submit`/`apply` put on PRs *of that
repository* that have none yet.

Writing goes through the shared module, which rewrites the option template and
carries the rest across, so `auto-config` can never cost the reader their
`[options]`.
"""

from __future__ import annotations

import datetime
import pathlib

from tabsdata_dev.common.core import config as common
from tabsdata_dev.common.core.errors import ToolError

from .options import doc
from .version import VERSION

COMMAND = "gsx"
REPOS = "repos"
SELF = "gsx"  # the [gsx] table: what gsx knows about the file itself


def path() -> pathlib.Path:
    return common.path(COMMAND)


def read() -> dict:
    """``{"version": ..., "repos": {slug: entry}}`` -- the shape gsx works in."""
    document = common.read(COMMAND)
    repos: dict[str, dict] = {}
    for slug, table in (document.get(REPOS) or {}).items():
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
    return {
        "version": str((document.get(SELF) or {}).get("version", "")),
        "repos": repos,
    }


def render_tables(config: dict) -> str:
    """gsx's own tables as TOML: `[gsx]`, then one per repository, sorted."""
    lines = [f"[{SELF}]", f"version = {common.toml_value(VERSION)}"]
    for slug in sorted(config.get("repos", {})):
        entry = config["repos"][slug]
        defaults = entry.get("defaults") or {}
        lines.append(f"\n[{REPOS}.{common.toml_value(slug)}]")
        lines.append(f"fetched = {common.toml_value(entry.get('fetched', ''))}")
        lines.append(f"labels = {common.toml_value(entry.get('labels', []))}")
        lines.append(f"reviewers = {common.toml_value(entry.get('reviewers', []))}")
        lines.append(
            f"default_labels = {common.toml_value(defaults.get('labels', []))}"
        )
        lines.append(
            f"default_reviewers = {common.toml_value(defaults.get('reviewers', []))}"
        )
    return "\n".join(lines)


def write(config: dict) -> pathlib.Path:
    """Rewrite the file: the option template as it stands, then gsx's tables."""
    try:
        return common.update(COMMAND, doc(), keep=render_tables(config))
    except ToolError:
        raise


def now() -> str:
    return datetime.datetime.now().astimezone().isoformat(timespec="seconds")
