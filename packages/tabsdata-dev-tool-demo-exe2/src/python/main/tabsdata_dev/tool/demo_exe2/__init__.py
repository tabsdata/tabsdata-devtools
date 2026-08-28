#
# Copyright 2026 Tabsdata Inc.
#

"""demo-exe2 -- a demo tool living in the demo-env2 toolset.

It prints its own name and nothing else. What it demonstrates is the plumbing
around it: a tool package pinned to exactly one deps-* bundle, dispatched by
`tdd` into that bundle's venv, and the smallest possible command that follows
docs/command-cli-guidelines.md through common.core.cli and common.core.render.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import cli, render

NAME = "demo-exe2"


def body(args, out: render.Renderer) -> int:
    out.debug("about to print")
    return out.ok(NAME, name=NAME)


def main() -> int:
    return cli.run(NAME, "demo tool in the demo-env2 toolset: prints its name", body)


if __name__ == "__main__":
    sys.exit(main())
