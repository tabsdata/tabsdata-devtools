#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the dataquality per-category suite JSONs.

The suite is a set of pub->tfr->sub test files under ``functions/`` (see
``functions/_harness.py``); this script is the single source of truth for how
those files are grouped into runnable suites. For each category it imports the
listed ``functions/dq_*.py`` modules, discovers their PublisherInfo /
TransformerInfo / SubscriberInfo objects, and writes ``<category>.json`` with the
three fixed collections (dq_src / dq_ops / dq_sink), the discovered functions,
and a detached trigger per publisher.

There is no union ``suite.json``: run the whole suite with a bare
``tdx-xp <cmd> --suite dataquality`` (which unions every ``*.json`` in the dir),
or one category with ``--suite dataquality/<category>``.

Adding a test: drop ``functions/dq_<name>.py`` (validate it with ``validate.py``),
add its stem to the right category in CATEGORIES below, and re-run:

    python suites/dataquality/gen_suites.py

Run it with a Python that can import ``tabsdatak`` (the EE build).
"""
from __future__ import annotations

import importlib
import json
import sys
from pathlib import Path

SUITE = Path(__file__).resolve().parent
FN_DIR = SUITE / "functions"
sys.path.insert(0, str(FN_DIR))

# category -> (comment, [file stems])
CATEGORIES: dict[str, tuple[str, list[str]]] = {
    "sign": (
        "Sign boolean classifiers (IsPositive / IsNegative / IsZero and the "
        "or-zero / not-zero variants) with Enrich + Summary over a numeric column; "
        "null -> NULL(255), nan -> NAN(254).",
        [
            "dq_is_positive",
            "dq_is_negative",
            "dq_is_zero",
            "dq_is_positive_or_zero",
            "dq_is_negative_or_zero",
            "dq_is_not_zero",
        ],
    ),
    "nullnan": (
        "Null/NaN boolean classifiers. Single-condition classifiers emit the "
        "reserved sentinel for the out-of-scope case (a nan row under IsNull -> "
        "NAN(254); a null row under IsNan -> NULL(255)); IsNullOrNan / "
        "IsNotNullNorNan fold both into a plain true/false (no sentinels).",
        [
            "dq_is_null",
            "dq_is_not_null",
            "dq_is_nan",
            "dq_is_not_nan",
            "dq_is_null_or_nan",
            "dq_is_not_null_nor_nan",
        ],
    ),
    "boolean": (
        "Boolean-column classifiers (IsTrue / IsFalse) over a Boolean column "
        "(no nan possible; null -> NULL sentinel).",
        ["dq_is_true", "dq_is_false"],
    ),
    "membership": (
        "Membership classifiers (IsIn / IsNotIn) with a values set; a null row is "
        "the NULL sentinel unless None is a member of the set.",
        ["dq_is_in", "dq_is_not_in"],
    ),
    "range": (
        "Range classifiers (IsBetween / IsNotBetween) with min_val / max_val and "
        "closed_on boundary inclusivity.",
        ["dq_is_between", "dq_is_not_between"],
    ),
    "string": (
        "String classifiers (HasLength length range; Matches / DoesNotMatch regex "
        "search) over a string column; null -> NULL sentinel, never nan.",
        ["dq_has_length", "dq_matches", "dq_does_not_match"],
    ),
    "categorizers": (
        "Categorizers / scales (Linear / Logarithmic / Exponential / Monomial / "
        "Identity scale + ScaleCategorizer): each buckets a numeric column into "
        "bins; the enrich column holds the bin index and the summary is "
        "dq.type='categorical' with dq.pNNN bin tallies plus under/over/nan/none.",
        [
            "dq_linear_scale",
            "dq_logarithmic_scale",
            "dq_exponential_scale",
            "dq_monomial_scale",
            "dq_identity_scale",
            "dq_scale_categorizer",
        ],
    ),
    "operators": (
        "Operators beyond plain Enrich + Summary: Enrich(to_table) and "
        "Summary(custom table) derived tables, Filter and Select (Filter removes "
        "the rows its criteria selects, redirecting them to to_table; Select "
        "copies them), a non-triggering Fail, a "
        "multi-classifier and a multi-column action, a multi-operator chain, and "
        "include_quality_columns carrying verdict columns into the output.",
        [
            "dq_enrich_to_table",
            "dq_summary_custom",
            "dq_filter",
            "dq_select",
            "dq_multi_classifier",
            "dq_fail_ok",
            "dq_multi_column",
            "dq_multi_operator",
            "dq_include_quality_columns",
        ],
    ),
    "criteria": (
        "Criteria and thresholds: AnyFailed row selection (vs AllOk), InBins / "
        "NotInBins category criteria over a categorizer verdict, and a "
        "non-triggering Fail with a PercentThreshold.",
        [
            "dq_any_failed",
            "dq_filter_in_bins",
            "dq_not_in_bins",
            "dq_fail_percent",
        ],
    ),
}


def assert_unique_table_names() -> None:
    """Fail loudly (offline) on any table-name collision within a shared collection.

    A bare ``--suite dataquality`` unions every category JSON over the SAME three
    collections, so each file's user table names must be unique across the whole
    suite. ``validate.py`` cannot catch this (it runs each file in isolation), so
    guard it here — this is exactly the collision `tdk fn register` rejects with
    "Tables [X] already exists in collection". Also asserts each file's
    ``DQCase.name`` equals its stem, which keeps the ``<name>__`` prefixes globally
    unique by construction (stems are unique filenames)."""
    seen: dict[str, dict[str, str]] = {"dq_src": {}, "dq_ops": {}}
    for _cat, (_comment, stems) in CATEGORIES.items():
        for stem in stems:
            mod = importlib.import_module(stem)
            case = getattr(mod, "CASE", None)
            if case is None:
                raise SystemExit(f"{stem}: no module-level CASE")
            if case.name != stem:
                raise SystemExit(
                    f"{stem}: DQCase name {case.name!r} must equal the file stem"
                )
            tables = {
                "dq_src": list(case.input_names),
                "dq_ops": sorted(set(case.main_tables) | set(case.output_names)),
            }
            for coll, names in tables.items():
                for t in names:
                    if t in seen[coll]:
                        raise SystemExit(
                            f"table-name collision in {coll!r}: {t!r} emitted by both "
                            f"{seen[coll][t]!r} and {stem!r} — give each file a unique "
                            f"DQCase(name=...) (defaults to the file stem)"
                        )
                    seen[coll][t] = stem


assert_unique_table_names()

COLLECTIONS = [
    {"name": "dq_src", "type": "datagen_in", "connection_template": "connection-file:connections/datagen_in.yaml", "group": "sources", "domains": {"D0": "dev"}},
    {"name": "dq_ops", "type": "transform", "group": "ops"},
    {"name": "dq_sink", "type": "trash_out", "connection_template": "connection-file:connections/trash_out.yaml", "group": "destinations", "domains": {"D0": "dev"}},
]
DOMAINS = [{"name": "dev", "system": "dev", "model": None, "data": None}]

KIND_TO_COLLECTION = {"PublisherInfo": "dq_src", "TransformerInfo": "dq_ops", "SubscriberInfo": "dq_sink"}


def discover(stem: str):
    """Return (functions, triggers) entries for one file, in pub/tfr/sub order."""
    mod = importlib.import_module(stem)
    found = {"PublisherInfo": [], "TransformerInfo": [], "SubscriberInfo": []}
    for name, obj in vars(mod).items():
        tn = type(obj).__name__
        if tn in found:
            found[tn].append(name)
    functions, triggers = [], []
    for kind in ("PublisherInfo", "TransformerInfo", "SubscriberInfo"):
        for fname in found[kind]:
            functions.append({"collection": KIND_TO_COLLECTION[kind], "functionpath": f"functions/{stem}.py::{fname}"})
            if kind == "PublisherInfo":
                triggers.append({"collection": "dq_src", "function": fname, "detached": True})
    return functions, triggers


def build(comment: str, stems: list[str]) -> dict:
    functions, triggers = [], []
    for stem in stems:
        f, t = discover(stem)
        functions += f
        triggers += t
    return {
        "_comment": f"DATAQUALITY · {comment} Every test is a pub->tfr->sub chain over dq_src (DataGenSrc) / dq_ops (@transformer with on_tables=[DataQuality]) / dq_sink (TrashDest): the transformer passes its input through and carries the data-quality action under test, the server applies it to the output tables (rewriting in place and/or registering derived tables), and the subscriber asserts each resulting table matches its authored expected frame (see functions/_harness.py). Generated by gen_suites.py.",
        "domains": DOMAINS,
        "collections": COLLECTIONS,
        "functions": functions,
        "triggers": triggers,
    }


def as_stages(doc: dict) -> list:
    """The suite as xp reads it: an ordered list of stages -- the ``_``
    annotations, then the domains (a domain-manifest, created in one parallel
    batch), collections, functions and triggers (each only when it has entries)
    and a monitor. Built as one object because that is how the sections are
    gathered; the order is what the stages are."""
    notes = {k: v for k, v in doc.items() if k.startswith("_")}
    stages = [notes] if notes else []
    # A suite's domains are its run's own: ${xp_name(x)} is <XP_ID>_x once read.
    own = "${xp_name(%s)}".__mod__
    if doc.get("domains"):
        domains = [{**d, "name": own(d["name"])} for d in doc["domains"]]
        stages.append({"domain-manifest": {"domains": domains}})
    for kind in ("collections", "functions", "triggers"):
        if not doc.get(kind):
            continue
        entries = doc[kind]
        if kind == "collections":
            entries = [
                {**c, "domains": {k: own(v) for k, v in c["domains"].items()}}
                if c.get("domains")
                else c
                for c in entries
            ]
        stages.append({kind: entries})
    stages.append({"monitor": {"time_out": "30m"}})
    return stages


def write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(as_stages(obj), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {path.relative_to(SUITE)}  ({len(obj['functions'])} fns, {len(obj['triggers'])} triggers)")


total_fns = total_trigs = 0
for cat, (comment, stems) in CATEGORIES.items():
    obj = build(comment, stems)
    write(SUITE / f"{cat}.json", obj)
    total_fns += len(obj["functions"])
    total_trigs += len(obj["triggers"])
print(f"\n{len(CATEGORIES)} categories, {total_fns} functions, {total_trigs} triggers "
      f"(run all with: tdx-xp <cmd> --suite dataquality)")
