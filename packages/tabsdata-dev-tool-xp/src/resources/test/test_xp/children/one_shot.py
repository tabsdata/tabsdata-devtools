#
# Copyright 2026 Tabsdata Inc.
#
"""Stands in for a `tdd xp one-shot` child: prints `ran` and its words, and
exits 1 when its selector, the third word, is one of the comma-separated
names in ONE_SHOT_FAIL."""

import os
import sys

print("ran", *sys.argv[1:])
failing = [name for name in os.environ.get("ONE_SHOT_FAIL", "").split(",") if name]
raise SystemExit(1 if sys.argv[3] in failing else 0)
