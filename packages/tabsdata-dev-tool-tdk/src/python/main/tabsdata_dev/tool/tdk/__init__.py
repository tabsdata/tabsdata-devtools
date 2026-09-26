#
# Copyright 2026 Tabsdata Inc.
#

"""tdk -- run tabsdata's tdk inside the venv last activated.

The tdk CLI is installed per project into a venv the user activates -- one
`tdd venv` manages, or any other -- not into a toolset, so this tool cannot
pin it: it finds that venv (common.core.managedvenv.select), says which, and
runs the real tdk there (common.core.launcher), from the cwd the user is in.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import launcher

NAME = "tdk"


def main() -> int:
    return launcher.run(
        NAME,
        "run tabsdata's tdk CLI inside the venv last activated (managed by tdd venv or not)",
    )


if __name__ == "__main__":
    sys.exit(main())
