#
# Copyright 2026 Tabsdata Inc.
#

"""km -- run tabsdata's km inside the venv last activated.

The km CLI is installed per project into a venv the user activates -- one
`tdd venv` manages, or any other -- not into a toolset, so this tool cannot
pin it: it finds that venv (common.core.managedvenv.select), says which, and
runs the real km there (common.core.launcher), from the cwd the user is in.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import launcher

NAME = "km"


def main() -> int:
    return launcher.run(
        NAME,
        "run tabsdata's km CLI inside the venv last activated (managed by tdd venv or not)",
    )


if __name__ == "__main__":
    sys.exit(main())
