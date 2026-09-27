#
# Copyright 2026 Tabsdata Inc.
#

"""jq -- run the machine's jq.

PyPI's `jq` is bindings to libjq without the command-line program, so there is
nothing to pin: this runs the jq on PATH, declared in bin-reqs.txt (the POSIX
shell half already needs it). The tool's own entry point is called `jq` too,
which is why the launcher looks past this venv's scripts dir.
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.core import launcher

NAME = "jq"
PROGRAM = "jq"


def main() -> int:
    return launcher.run_program(
        NAME,
        PROGRAM,
        "run jq, the JSON processor installed on the machine",
        pinned=False,
    )


if __name__ == "__main__":
    sys.exit(main())
