#
# Copyright 2026 Tabsdata Inc.
#

"""Write the pids `instances.pids(NAME)` finds into ANSWER, from under a
shell whose own command line carries the instance folder.

    ask_pids.py NAME ANSWER
"""

import pathlib
import sys

from tabsdata_dev.tool.smoke import instances

name, answer = sys.argv[1], pathlib.Path(sys.argv[2])
answer.write_text(f"{instances.pids(name)}\n")
