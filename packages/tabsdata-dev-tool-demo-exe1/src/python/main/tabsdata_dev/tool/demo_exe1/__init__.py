#
# Copyright 2026 Tabsdata Inc.
#

"""demo-exe1 -- a demo tool living in the demo-env1 toolset.

It prints its own name and nothing else. What it demonstrates is the plumbing
around it: a tool package pinned to exactly one deps-* bundle, dispatched by
`tdd` into that bundle's venv.
"""

from __future__ import annotations

import sys

NAME = "demo-exe1"


def main() -> int:
    print(NAME)
    return 0


if __name__ == "__main__":
    sys.exit(main())
