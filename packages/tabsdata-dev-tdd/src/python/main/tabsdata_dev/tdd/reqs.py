#
# Copyright 2026 Tabsdata Inc.
#

"""Checking external binary requirements. Standard library only.

Reqs are read from the catalog rather than the source tree, so this works
before tdd-install and from a wheel install -- checking a fresh machine's
prerequisites is exactly when no environment exists yet.
"""

from __future__ import annotations

import shutil

from . import catalog as catalog_mod
from . import render


def check(tool: str | None, out: render.Renderer) -> int:
    catalog = catalog_mod.shipped()
    # Both halves declare binaries the same way; the shell ones are marked so
    # the report reads like `tdd help`.
    entries = {name: (entry, "") for name, entry in catalog["tools"].items()}
    entries.update(
        (name, (entry, " (shell)")) for name, entry in catalog.get("shell", {}).items()
    )

    if tool is not None:
        if tool not in entries:
            return out.error(f"unknown tool or shell command {tool!r}")
        selected = {tool: entries[tool]}
    else:
        selected = entries

    missing: list[str] = []
    checked = 0
    for name, (entry, label) in sorted(selected.items()):
        reqs = entry.get("reqs", [])
        if not reqs:
            out.info(f"{name}{label}: no external requirements", command_name=name)
            continue
        for binary in reqs:
            # Ambient PATH on purpose: a req is something the machine must
            # already provide, not something a toolset venv can supply.
            found = shutil.which(binary)
            checked += 1
            if found:
                out.info(
                    f"{name}{label}: [ok] {binary} -> {found}",
                    command_name=name,
                    binary=binary,
                    path=found,
                )
            else:
                missing.append(f"{name}: {binary}")
                out.warn(
                    f"{name}{label}: [missing] {binary}",
                    command_name=name,
                    binary=binary,
                )
    if missing:
        return out.error(
            f"{len(missing)} required binaries missing: {', '.join(missing)}",
            missing=missing,
        )
    return out.ok(f"all {checked} required binaries present", checked=checked)
