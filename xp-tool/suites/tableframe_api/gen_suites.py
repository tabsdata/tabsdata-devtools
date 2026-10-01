#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the tableframe_api per-category suite JSONs.

The suite is a set of pub->tfr->sub test files under ``functions/`` (see
``functions/_harness.py``); this script is the single source of truth for how
those files are grouped into runnable suites. For each category it imports the
listed ``functions/tf_*.py`` modules, discovers their PublisherInfo /
TransformerInfo / SubscriberInfo objects, and writes ``<category>.json`` -- a
list of stages, as xp reads a suite: the comment, the dev domain, the three
fixed collections (tf_src / tf_ops / tf_sink), the discovered functions, a
detached trigger per publisher and a monitor.

There is no union ``suite.json``: run every category with a bare
``tdd xp one-shot --suite tableframe_api`` (a directory is one lane per
``*.json`` in it), or one with ``--suite tableframe_api/<category>``.

Adding a test: drop ``functions/tf_<op>.py`` (validate it with ``validate.py``),
add its stem to the right category in CATEGORIES below, and re-run:

    python xp-tool/suites/tableframe_api/gen_suites.py

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
    "frame_reshape": (
        "Column-shaping frame ops: select, with_columns, rename, drop, cast, unnest, "
        "getitem-slicing, multi-output projection, and deeper param combos.",
        ["tf_select", "tf_split", "tf_with_columns", "tf_rename", "tf_drop", "tf_cast",
         "tf_unnest", "tf_getitem", "tf_frame_params"],
    ),
    "frame_filter": (
        "Row-set frame ops: filter, unique, drop_nulls, drop_nans, fill_null, fill_nan.",
        ["tf_filter", "tf_unique", "tf_drop_nulls", "tf_drop_nans", "tf_fill_null", "tf_fill_nan"],
    ),
    "frame_order": (
        "Order/slice frame ops: sort, head/tail/limit/slice/first/last, clear.",
        ["tf_sort", "tf_slice", "tf_clear"],
    ),
    "frame_join": (
        "join strategies (inner/left/right/full/outer/semi/anti/cross), left_on/right_on, "
        "suffix, and multi-way (triple/quadruple) + join-with-aggregation.",
        ["tf_join", "tf_join_multi"],
    ),
    "frame_concat": (
        "functions.concat (vertical / diagonal).",
        ["tf_concat"],
    ),
    "frame_group_by": (
        "group_by(...).agg aggregations and the direct reduction shortcuts "
        "(min/max/mean/median/n_unique/count/len).",
        ["tf_group_by_agg", "tf_group_by_reductions"],
    ),
    "expr_arithmetic": (
        "Expr arithmetic operators + methods (+ - * / // % **, add/sub/..), unary "
        "(-/+/abs) and reflected (right-hand) operators.",
        ["tf_expr_arith_ops", "tf_expr_arith_methods", "tf_expr_unary_ops",
         "tf_expr_reflected_ops"],
    ),
    "expr_comparison": (
        "Expr comparison operators and methods (== != < <= > >= and eq/ne/lt/...).",
        ["tf_expr_cmp_ops", "tf_expr_cmp_methods"],
    ),
    "expr_boolean": (
        "Expr boolean operators and methods (& | ^ ~ and and_/or_/xor/not_).",
        ["tf_expr_bool_ops", "tf_expr_bool_methods"],
    ),
    "expr_nullnan": (
        "Expr null/nan predicates and fills (is_null/is_nan/is_finite/fill_null/fill_nan).",
        ["tf_expr_null", "tf_expr_nan"],
    ),
    "expr_rounding": (
        "Expr rounding/clamping (floor/ceil/round/round_sig_figs/clip/sign/abs).",
        ["tf_expr_round", "tf_expr_clip_sign"],
    ),
    "expr_math": (
        "Expr math (trig / hyperbolic / degrees-radians / exp / log / sqrt / cbrt).",
        ["tf_expr_trig", "tf_expr_hyper", "tf_expr_explog"],
    ),
    "expr_aggregation": (
        "Expr aggregations (min/max/sum/mean/median/n_unique/count/len/first/last/is_unique).",
        ["tf_expr_agg", "tf_expr_firstlast"],
    ),
    "expr_selection": (
        "Expr selection/ranking/misc (is_in/is_between/rank/diff, hash/cast, lit, "
        "reinterpret, expr-level filter/slice, and deeper param combos).",
        ["tf_expr_isin_between", "tf_expr_rank_diff", "tf_expr_misc", "tf_lit",
         "tf_expr_reinterpret", "tf_expr_filter_slice", "tf_expr_params"],
    ),
    "expr_string": (
        "Expr .str namespace (case/len/strip/pad/contains/replace/slice/extract/parse) "
        "and deeper param combos.",
        ["tf_str_case", "tf_str_len", "tf_str_strip", "tf_str_pad", "tf_str_contains",
         "tf_str_replace", "tf_str_slice", "tf_str_extract", "tf_str_parse", "tf_str_params"],
    ),
    "expr_datetime": (
        "Expr .dt namespace (components/extract/boundary/convert/duration/timezone) and "
        "add_business_days/combine/datetime/with_time_unit.",
        ["tf_dt_component", "tf_dt_component2", "tf_dt_extract", "tf_dt_boundary",
         "tf_dt_convert", "tf_dt_duration", "tf_dt_tz", "tf_dt_more"],
    ),
    "dtypes": (
        "Datatype coverage: cast to narrow/parametric/nested dtypes (UInt8/Int16/Int32/"
        "Float32/Boolean/Decimal/Categorical) and carry Struct/List, with dtype-asserting "
        "special verifiers.",
        ["tf_dtypes"],
    ),
    "failing": (
        "KNOWN DIVERGENCES catalog — behaviours that do NOT match polars (system-column "
        "leakage in rename(callable)/unique/group_by reductions, lazy column subscription), "
        "asserted straight so this sub-suite is EXPECTED TO FAIL.",
        ["tf_failing"],
    ),
}

COLLECTIONS = [
    {"name": "tf_src", "type": "datagen_in", "connection_template": "connection-file:connections/datagen_in.yaml", "group": "sources", "domains": {"D0": "dev"}},
    {"name": "tf_ops", "type": "transform", "group": "ops"},
    {"name": "tf_sink", "type": "trash_out", "connection_template": "connection-file:connections/trash_out.yaml", "group": "destinations", "domains": {"D0": "dev"}},
]
DOMAINS = [{"name": "dev", "system": "dev", "model": None, "data": None}]

KIND_TO_COLLECTION = {"PublisherInfo": "tf_src", "TransformerInfo": "tf_ops", "SubscriberInfo": "tf_sink"}


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
                triggers.append({"collection": "tf_src", "function": fname, "detached": True})
    return functions, triggers


def build(comment: str, stems: list[str]) -> dict:
    functions, triggers = [], []
    for stem in stems:
        f, t = discover(stem)
        functions += f
        triggers += t
    return {
        "_comment": f"TABLEFRAME_API · {comment} Every test is a pub->tfr->sub chain over tf_src (DataGenSrc) / tf_ops (@transformer) / tf_sink (TrashDest): the transformer applies the operation(s) under test via the TableFrame API and the subscriber re-applies the same operation in polars and asserts equality (see functions/_harness.py). Generated by gen_suites.py.",
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
      f"(run all with: tdd xp one-shot --suite tableframe_api)")
