#
# Copyright 2026 Tabsdata Inc.
#

"""A stand-in for a km process: it carries an instance folder on its command
line and sleeps until it is ended -- or, with --ignore-term, until it is
killed, like a km winding down that will not take a TERM.

    sleeper.py FOLDER [--ignore-term]
"""

import signal
import sys
import time

if "--ignore-term" in sys.argv[2:]:
    signal.signal(signal.SIGTERM, signal.SIG_IGN)
print("ready", flush=True)
while True:
    time.sleep(0.1)
