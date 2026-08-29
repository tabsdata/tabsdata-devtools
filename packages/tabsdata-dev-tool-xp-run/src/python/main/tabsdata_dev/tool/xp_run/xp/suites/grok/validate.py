#
# Copyright 2026 Tabsdata Inc.
#
"""Offline validator for the grok suite.

Imports every ``functions/gk_*.py`` (which runs the @publisher / @transformer /
@subscriber signature validation), then exercises it offline, per file kind:

  * a TEST (``gk_<name>.py``, module-level ``CASE``) runs ``CASE.selfcheck()`` — every
    grok call under test applied to the entity's embedded ``SAMPLE`` lines, with the same
    expectations the subscriber asserts live;
  * an EXAMPLE (``gk_ex_<name>.py``, module-level ``demo()``) runs ``demo()`` — its
    transformer bodies over its own sample lines — and reports the shape of each table it
    produces. Examples assert nothing, so this only proves they run and parse.

Reports OK / FAIL per file.

It does NOT test the LOG read (``SrcFileFormat.LOG`` -> ``file``/``message``), the storage
round-trip or the registration path; that is what ``tdx-xp oneshot --suite grok/<category>``
covers. A green run here means "the patterns and the expectations agree with the grok
engine"; a green live run then means "and the whole flow preserves that".

Run it with a Python that can import ``tabsdatak`` (the EE build):

    python suites/grok/validate.py                        # all gk_*.py
    python suites/grok/validate.py gk_split gk_country     # only these stems
    python suites/grok/validate.py gk_ex_cities            # one example
"""
from __future__ import annotations

import importlib
import sys
import traceback
from pathlib import Path

FN_DIR = (Path(__file__).resolve().parent / "functions").resolve()
sys.path.insert(0, str(FN_DIR))

# Extra args are specific stems to validate (e.g. "gk_split"); with none, validate every
# gk_*.py in the functions dir.
wanted = [a[:-3] if a.endswith(".py") else a for a in sys.argv[1:]]
files = [FN_DIR / f"{w}.py" for w in wanted] if wanted else sorted(FN_DIR.glob("gk_*.py"))

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
    demo = getattr(mod, "demo", None)
    if case is None and callable(demo):
        # An example: no expectations to check, so run its demo() and report what each
        # transformer produced — a wrong pattern shows up as a table with no rows.
        try:
            frames = {name: tf._to_polars_lf().collect() for name, tf in demo().items()}
            shapes = ", ".join(f"{n} {df.height}x{df.width}" for n, df in frames.items())
            n_ok += 1
            print(f"OK    {stem}  <example>  [{shapes}]")
        except Exception as e:
            n_fail += 1
            print(f"FAIL  {stem}  <example>: {type(e).__name__}: {e}")
            traceback.print_exc()
        continue
    if case is None:
        n_fail += 1
        print(f"FAIL  {stem}: no module-level CASE (test) or demo() (example)")
        continue
    names = ", ".join(case.output_names)
    try:
        case.selfcheck()
        n_ok += 1
        print(f"OK    {stem}  <{case.entity}>  [{names}]")
    except Exception as e:
        n_fail += 1
        # selfcheck() runs every grok call independently and raises one AssertionError
        # listing each failing call + reason, so just surface it verbatim.
        print(f"FAIL  {stem}  <{case.entity}>: {e if str(e) else repr(e)}")

print(f"\n{n_ok} ok, {n_fail} failed ({len(files)} file(s))")
raise SystemExit(1 if n_fail else 0)
