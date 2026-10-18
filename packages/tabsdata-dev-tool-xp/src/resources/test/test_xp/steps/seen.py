#
# Copyright 2026 Tabsdata Inc.
#
"""Write what the step was handed -- argv, cwd, the run's XP_* names and
the first PATH entry -- to seen.json beside this script; and import the tdd
module, which must be on its path."""

import json
import os
import pathlib
import sys

from tdd import note, tdd  # noqa: F401

NAMES = ("XP_WORK_DIR", "XP_PROJECT", "XP_ID", "XP_SHORT_ID", "XP_SUITE_RUN")

seen = {
    "argv": sys.argv[1:],
    "cwd": os.getcwd(),
    "env": {name: os.environ[name] for name in NAMES},
    "path0": os.environ["PATH"].split(os.pathsep)[0],
}
pathlib.Path(__file__).with_name("seen.json").write_text(json.dumps(seen))
