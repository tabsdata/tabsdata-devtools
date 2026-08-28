#
# Copyright 2026 Tabsdata Inc.
#

"""`system` -- manage external systems for testing: databases, object stores, services (docker, cloud, remote).

A thin entry point: the whole family lives in tabsdata_dev.common.systems, shared
by the `systems` and `salesforce` toolsets; this tool only says which command it
is (``system`` family, running as ``system``).
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.systems import main as family_main

TOOL = "system"


def main() -> int:
    return family_main.run(TOOL)


if __name__ == "__main__":
    sys.exit(main())
