#
# Copyright 2026 Tabsdata Inc.
#

"""Checking external binary requirements. Standard library only.

Reqs are read from the catalog rather than the source tree, so this works
before `tdd init` and from a wheel install -- checking a fresh machine's
prerequisites is exactly when no environment exists yet.
"""

from __future__ import annotations

import shutil

from . import catalog as catalog_mod

OK = "[ok]     "
MISSING = "[missing]"


def check(tool: str | None) -> int:
    catalog = catalog_mod.shipped()
    # Both halves declare binaries the same way; the shell ones are marked so
    # the report reads like `tdd help`.
    entries = {name: (entry, "") for name, entry in catalog["tools"].items()}
    entries.update(
        (name, (entry, " (shell)")) for name, entry in catalog.get("shell", {}).items()
    )

    if tool is not None:
        if tool not in entries:
            print(f"tdd: unknown tool or shell command {tool!r}")
            return 2
        selected = {tool: entries[tool]}
    else:
        selected = entries

    missing = 0
    for name, (entry, label) in sorted(selected.items()):
        reqs = entry.get("reqs", [])
        print(f"{name}{label}:" + ("" if reqs else "  (no external requirements)"))
        for binary in reqs:
            # Ambient PATH on purpose: a req is something the machine must
            # already provide, not something a toolset venv can supply.
            found = shutil.which(binary)
            if found:
                print(f"  {OK} {binary:<20} {found}")
            else:
                missing += 1
                print(f"  {MISSING} {binary:<20}")
    return 1 if missing else 0
