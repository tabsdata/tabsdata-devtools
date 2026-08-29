#
# Copyright 2026 Tabsdata Inc.
#
"""Offline validator for the tableframe_api suite.

Imports every ``functions/tf_*.py`` (which runs the @publisher / @transformer /
@subscriber signature validation), then runs its module-level ``CASE.selfcheck()``
— a ``TableFrame.from_polars`` round-trip + compare against the equivalent polars
result. Reports OK / FAIL per file and per check. It does NOT test the storage
round-trip; that is what ``tdx-xp speedy --suite tableframe_api/<category>``
covers.

Run it with a Python that can import ``tabsdatak`` (the EE build):

    python suites/tableframe_api/validate.py                 # all tf_*.py
    python suites/tableframe_api/validate.py tf_sort tf_cast # only these stems
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

FN_DIR = (Path(__file__).resolve().parent / "functions").resolve()
sys.path.insert(0, str(FN_DIR))

# Extra args are specific stems to validate (e.g. "tf_sort tf_cast"); with none,
# validate every tf_*.py in the functions dir.
wanted = [a[:-3] if a.endswith(".py") else a for a in sys.argv[1:]]
if wanted:
    files = [FN_DIR / f"{w}.py" for w in wanted]
else:
    files = sorted(p for p in FN_DIR.glob("tf_*.py"))

n_ok = n_fail = 0
for p in files:
    stem = p.stem
    try:
        mod = importlib.import_module(stem)
    except Exception as e:
        n_fail += 1
        print(f"FAIL  {stem}: import/signature error: {type(e).__name__}: {e}")
        traceback.print_exc()
        continue
    case = getattr(mod, "CASE", None)
    if case is None:
        n_fail += 1
        print(f"FAIL  {stem}: no module-level CASE")
        continue
    names = ", ".join(case.output_names)
    try:
        case.selfcheck()
        n_ok += 1
        print(f"OK    {stem}  [{names}]")
    except Exception as e:
        n_fail += 1
        # selfcheck() runs every check independently and raises one AssertionError
        # listing each failing check + reason, so just surface it verbatim.
        msg = str(e) if str(e) else repr(e)
        print(f"FAIL  {stem}: {type(e).__name__}: {msg}")

print(f"\n==== {n_ok} ok, {n_fail} fail, {len(files)} files ====")
sys.exit(1 if n_fail else 0)
