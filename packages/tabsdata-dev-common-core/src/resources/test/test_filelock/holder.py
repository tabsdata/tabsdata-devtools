#
# Copyright 2026 Tabsdata Inc.
#
"""Hold the lock at argv[1] for argv[2] seconds, from another process; says
"held" once it has it."""

import pathlib
import sys
import time

from tabsdata_dev.common.core import filelock

with filelock.held(pathlib.Path(sys.argv[1])):
    print("held", flush=True)
    time.sleep(float(sys.argv[2]))
