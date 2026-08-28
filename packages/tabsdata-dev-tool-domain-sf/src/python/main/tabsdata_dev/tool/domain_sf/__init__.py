#
# Copyright 2026 Tabsdata Inc.
#

"""`domain-sf` -- domain, running in the salesforce toolset (the org's data plane).

A thin entry point: the whole family lives in tabsdata_dev.common.systems, shared
by the `systems` and `salesforce` toolsets; this tool only says which command it
is (``domain`` family, running as ``domain-sf``).
"""

from __future__ import annotations

import sys

from tabsdata_dev.common.systems import main as family_main

TOOL = "domain-sf"


def main() -> int:
    return family_main.run(TOOL)


if __name__ == "__main__":
    sys.exit(main())
