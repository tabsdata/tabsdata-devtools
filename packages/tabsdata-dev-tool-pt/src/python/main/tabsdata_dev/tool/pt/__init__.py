#
# Copyright 2026 Tabsdata Inc.
#

"""pt -- run parquet-tools, which the xp toolset pins.

parquet-tools caps pandas below 3, which is why it lives in `deps-xp` and not
in `systems`; xp's check scripts already read table versions with it, so this
tool shares that venv rather than resolving the same pin a second time.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import launcher

NAME = "pt"
PROGRAM = "parquet-tools"


def main() -> int:
    return launcher.run_program(
        NAME,
        PROGRAM,
        "run parquet-tools (show, csv, inspect a parquet file) from the xp toolset",
        pinned=True,
    )


if __name__ == "__main__":
    sys.exit(main())
