#
# Copyright 2026 Tabsdata Inc.
#
"""The tdd module as a python step uses it: a call that works, one that
fails, and a note."""

from tdd import TddError, note, tdd

print(tdd("pqt", "csv", "f.parquet").strip())
try:
    tdd("boom")
except TddError as exc:
    print("failed", exc.status, exc.output.strip())
note("812 rows,\n  3 rows/s")
