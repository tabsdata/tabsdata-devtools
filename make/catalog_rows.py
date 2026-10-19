#
# Copyright 2026 Tabsdata Inc.
#
"""Rows from a tdd dir's catalog.json, one per line, for the cargo-make tasks
to loop over. Standard library only: it runs on the tdd env's python.

    catalog_rows.py tools CATALOG      TOOL TOOLSET PACKAGE, by tool name
    catalog_rows.py commons CATALOG    PACKAGE TOOLSET, each common-* in each
                                       toolset env it is a member of
    catalog_rows.py configs CATALOG    KIND COMMAND, every command by name;
                                       KIND is tool, shell or launcher
"""

import json
import pathlib
import sys

COMMON_PREFIX = "tabsdata-dev-common-"


def tools(catalog: dict) -> list[str]:
    return [
        f"{name} {entry['toolset']} {entry['package']}"
        for name, entry in sorted(catalog["tools"].items())
    ]


def commons(catalog: dict) -> list[str]:
    return [
        f"{member} {toolset}"
        for toolset in catalog["toolsets"]
        for member in catalog["members"][toolset]
        if member.startswith(COMMON_PREFIX)
    ]


def configs(catalog: dict) -> list[str]:
    """A launcher owns no options -- `tdd tdk config` is the program's own
    `config` -- so it is named apart, for `setup` to skip; a shell command's
    config action is reached through a loader, a tool's through tdd-exe."""
    kinds = {
        name: "launcher" if entry.get("launcher") else "tool"
        for name, entry in catalog["tools"].items()
    }
    kinds.update((name, "shell") for name in catalog["shell"])
    return [f"{kind} {name}" for name, kind in sorted(kinds.items())]


def main() -> int:
    word, path = sys.argv[1], sys.argv[2]
    catalog = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = {"tools": tools, "commons": commons, "configs": configs}[word](catalog)
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
