#
# Copyright 2026 Tabsdata Inc.
#

"""tdkserver -- run tabsdata's tdkserver inside the active managed venv.

The tdkserver process is installed per project into a venv that `tdd venv` manages, not
into a toolset, so this tool cannot pin it: it finds the venv through
$TDD_VENV and runs the real tdkserver there (common.core.launcher), from the cwd
the user is in.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import launcher

NAME = "tdkserver"


def main() -> int:
    return launcher.run(
        NAME, "run tabsdata's tdkserver inside the managed venv named by $TDD_VENV"
    )


if __name__ == "__main__":
    sys.exit(main())
