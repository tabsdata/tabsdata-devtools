#
# Copyright 2026 Tabsdata Inc.
#

"""What gsx keeps in ``<tdd_dir>/gsx.toml``: one table per repository.

The file is every command's config file (`common.core.config`): its
``[options]`` table holds what gsx's own options default to, and gsx adds
``[approver-credentials]`` and one ``[repo."OWNER/NAME"]`` table per repository. Labels and
collaborators differ per repository -- a flat list would validate one
repository's names against another's -- and so do the two ``default_*`` lists,
which are the labels and reviewers `submit`/`apply` put on PRs *of that
repository* that have none yet.

Writing goes through the shared module, which rewrites the option template and
carries the rest across, so a refresh can never cost the reader their
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
REPO = "repo"  # [repo."OWNER/NAME"], one per repository; [repo] carries version
ALIASES = "reviewer-aliases"  # nickname -> login, file-wide: a login is a person
CREDS = "approver-credentials"  # where `approve` reads a review token from
_OLD_SELF = "gsx"  # both of those lived in a [gsx] table first; read, never written
# Where `approve` reads an approver's review token from: 1Password, the way
# gtx does it -- vault dev_ci, item GitHub, field <approver>.review.pat.
# Literals with a home in the file, so a different vault is an edit, not a
# variable in someone's environment.
APPROVE_DEFAULTS = {
    "approve_vault": "dev_ci",
    "approve_item": "GitHub",
    "approve_pat_suffix": ".review.pat",
}
#: The team, shipped so an alias works before anyone has a config file. A file
#: entry of the same name wins, the way APPROVE_DEFAULTS works: these are a
#: starting point, not a lock. Ordered as written, not sorted, so the table
#: reads as a list of people rather than an index.
ALIAS_DEFAULTS = {
    "dimas": "aoinokimi",
    "joaquin": "joaquin041",
    "tucu": "tucu0",
    "daniel": "adaydan-tabsdata",
    "arvind": "aptabs",
    "shreyas": "shreyasvan001",
    "david": "tabsdavid",
}

_OLD_REPO = "repos"  # what the table was called first; read, never written


def path() -> pathlib.Path:
    return common.path(COMMAND)


def read() -> dict:
    """``{"version", "repos": {slug: entry}, "aliases": {}}`` -- gsx's shape."""
    document = common.read(COMMAND)
    repos: dict[str, dict] = {}
    # `repos` was this table's first name; read either, write only `repo`, so a
    # file written before the rename migrates the next time gsx writes.
    tables = document.get(REPO) or document.get(_OLD_REPO) or {}
    for slug, table in tables.items():
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
    # `version` marks how fresh the repo tables are, so it sits on [repo] with
    # them; it was in [gsx] first, which is read for a file written before this.
    legacy = document.get(_OLD_SELF) or {}
    version = str((document.get(REPO) or {}).get("version", legacy.get("version", "")))
    aliases = {
        **ALIAS_DEFAULTS,
        **{
            str(name): str(login)
            for name, login in (document.get(ALIASES) or {}).items()
            if isinstance(login, str)
        },
    }
    table = document.get(CREDS) or legacy
    return {
        "version": version,
        "approve": {
            key: str(table.get(key, default))
            for key, default in APPROVE_DEFAULTS.items()
        },
        "repos": repos,
        "aliases": aliases,
    }


def render_tables(config: dict) -> str:
    """gsx's own tables as TOML: `[approver-credentials]`, the aliases, then
    `[repo]` with its version and one sub-table per repository."""
    approve = config.get("approve") or {}
    lines = [
        f"[{CREDS}]",
        "# where `approve` reads an approver's review token from:",
        "# op://<vault>/<item>/<login><suffix>",
    ]
    for key, default in APPROVE_DEFAULTS.items():
        lines.append(f"{key} = {common.toml_value(approve.get(key, default))}")
    aliases = config.get("aliases") or {}
    lines.append(f"\n[{ALIASES}]")
    lines.append('# a name of your own for a reviewer: <alias> = "<github login>",')
    lines.append("# usable anywhere a --reviewer: value is (they are validated after")
    lines.append(
        "# the alias is resolved). A login is a person, so these are file-wide."
    )
    # The shipped ones first, in the order they are declared, then anything the
    # reader added, sorted: a list of people, not an index.
    shipped = [n for n in ALIAS_DEFAULTS if n in aliases]
    for name in shipped + sorted(set(aliases) - set(shipped)):
        lines.append(
            f"{common.toml_value(name).strip(chr(34))} = {common.toml_value(aliases[name])}"
        )
    repos = sorted(config.get("repos", {}))
    lines.append(
        "\n# One table per repository, WRITTEN AND MAINTAINED BY gsx: `fetched`,"
        "\n# `labels` and `reviewers` are refreshed automatically and any edit to"
        "\n# them is overwritten. The two default_* lists are yours -- what"
        "\n# submit/apply put on that repository's PRs that have none yet."
        "\n# `version` is the gsx that last refreshed them."
    )
    lines.append(f"\n[{REPO}]")
    lines.append(f"version = {common.toml_value(VERSION)}")
    for slug in repos:
        entry = config["repos"][slug]
        defaults = entry.get("defaults") or {}
        lines.append(f"\n[{REPO}.{common.toml_value(slug)}]")
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
