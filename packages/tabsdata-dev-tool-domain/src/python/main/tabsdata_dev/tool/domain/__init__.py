#
# Copyright 2026 Tabsdata Inc.
#

"""`domain` -- manage domains inside systems: schemas, generated data, change sets.

A thin entry point: the whole family lives in tabsdata_dev.common.systems, shared
by the `systems` and `salesforce` toolsets; this tool only says which command it
is (``domain`` family, running as ``domain``).
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.systems import main as family_main

TOOL = "domain"


def main() -> int:
    return family_main.run(TOOL)


if __name__ == "__main__":
    sys.exit(main())
