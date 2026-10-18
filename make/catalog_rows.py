#
# Copyright 2026 Tabsdata Inc.
#
"""Rows from a tdd dir's catalog.json, one per line, for `cargo make
test-toolsets` to loop over. Standard library only: it runs on the tdd env's
python.

    catalog_rows.py tools CATALOG      TOOL TOOLSET PACKAGE, by tool name
    catalog_rows.py commons CATALOG    PACKAGE TOOLSET, each common-* in each
                                       toolset env it is a member of
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


def main() -> int:
    word, path = sys.argv[1], sys.argv[2]
    catalog = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    rows = {"tools": tools, "commons": commons}[word](catalog)
    for row in rows:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
