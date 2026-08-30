#
# Copyright 2026 Tabsdata Inc.
#
"""Generate the grok per-category suite JSONs.

The suite has two kinds of files under ``functions/``, and one category per kind:

  * ``gk_<name>.py``    — TESTS: pub->tfr->sub chains built from the ``_harness`` case
    objects, asserting what each grok call must produce (category ``world_csv``).
  * ``gk_ex_<name>.py`` — EXAMPLES: the same grok calls written the way you would write
    them in your own project — plain transformer bodies, no harness — landing their
    output as parquet (category ``examples``).

This script is the single source of truth for how those files are grouped into runnable
suites. For each category it imports the listed modules, discovers their PublisherInfo /
TransformerInfo / SubscriberInfo objects, and writes ``<category>.json`` with the
category's domains and collections, the discovered functions, and a detached trigger per
publisher.

There is no union ``suite.json``: run the whole suite with a bare
``tdx-xp <cmd> --suite grok`` (which fans out over every ``*.json`` in the dir, one
instance per file), or one category with ``--suite grok/<category>``.

Adding a test (or an example): drop ``functions/gk_<name>.py`` /
``functions/gk_ex_<name>.py`` (validate it with ``validate.py``), add its stem to the
right category below, and re-run:

    python suites/grok/gen_suites.py

Run it with a Python that can import ``tabsdatak`` (the EE build).
"""
from __future__ import annotations

import importlib
import json
import sys
from dataclasses import dataclass
from pathlib import Path

SUITE = Path(__file__).resolve().parent
FN_DIR = SUITE / "functions"
sys.path.insert(0, str(FN_DIR))

# The source domain of both categories is a FILE domain carrying the world model: its data
# plane stages csv/<entity>_<stamp>.csv (plus ndjson/parquet) under the domain root, which
# is what the LOG publishers read.
WORLD_DOMAIN = {"name": "fs_world_xs", "system": "fs", "model": "world", "data": "xs"}
# `dev` backs the TrashDest sink of the tests (a no-op domain, no keys); `fs_out` is a
# plain file domain the examples write their parquet output into.
DEV_DOMAIN = {"name": "dev", "system": "dev", "model": None, "data": None}
OUT_DOMAIN = {"name": "fs_out", "system": "fs", "model": None, "data": None}
# The S3 twins: the same world staging, in a bucket prefix instead of a directory.
S3_WORLD_DOMAIN = {"name": "s3_world_xs", "system": "s3", "model": "world", "data": "xs"}
S3_OUT_DOMAIN = {"name": "s3_out", "system": "s3", "model": None, "data": None}


@dataclass(frozen=True)
class Layout:
    """Where a category's functions land: one collection per function kind, plus the
    domains/collections its suite JSON declares and the chain blurb for its ``_comment``.

    Each JSON is its own suite (``--suite grok/<category>``; a bare ``--suite grok`` fans
    out over the dir, one instance per file), so two categories may name their collections
    freely — nothing is shared between them at run time."""

    src: str            # collection for @publisher
    ops: str            # collection for @transformer
    sink: str           # collection for @subscriber
    domains: list[dict]
    collections: list[dict]
    chain: str          # appended to the category comment: what the chain is

    @property
    def kinds(self) -> dict[str, str]:
        return {"PublisherInfo": self.src, "TransformerInfo": self.ops,
                "SubscriberInfo": self.sink}


# The TESTS: publishers read the staged CSV as lines, transformers run the grok calls
# under test, subscribers assert the parse and discard it.
TEST_LAYOUT = Layout(
    src="gk_src", ops="gk_ops", sink="gk_sink",
    domains=[WORLD_DOMAIN, DEV_DOMAIN],
    collections=[
        {"name": "gk_src", "type": "local_file_in",
         "connection_template": "connection-file:connections/local_file_in.yaml",
         "group": "sources", "domains": {"D0": "fs_world_xs"}},
        {"name": "gk_ops", "type": "transform", "group": "ops"},
        {"name": "gk_sink", "type": "trash_out",
         "connection_template": "connection-file:connections/trash_out.yaml",
         "group": "destinations", "domains": {"D0": "dev"}},
    ],
    chain=(
        "Every test is a pub->tfr->sub chain over gk_src (LocalFileSrc with "
        "SrcFileFormat.LOG, reading one staged world CSV as LINES: columns `file` + "
        "`message`) / gk_ops (@transformer, applies the grok calls under test) / gk_sink "
        "(TrashDest, asserts the parse and discards). polars has no grok, so the "
        "expectations are authored against the world sample data's known content and are "
        "checked offline too (see functions/_harness.py, validate.py)."
    ),
)

# The EXAMPLES: the same reads, but the transformers are written the way a user writes
# them — grok inline in the function body — and the result is landed as parquet.
EXAMPLE_LAYOUT = Layout(
    src="gk_logs", ops="gk_marts", sink="gk_out",
    domains=[WORLD_DOMAIN, OUT_DOMAIN],
    collections=[
        {"name": "gk_logs", "type": "local_file_in",
         "connection_template": "connection-file:connections/local_file_in.yaml",
         "group": "sources", "domains": {"D0": "fs_world_xs"}},
        {"name": "gk_marts", "type": "transform", "group": "marts"},
        {"name": "gk_out", "type": "local_file_out",
         "connection_template": "connection-file:connections/local_file_out.yaml",
         "group": "destinations", "domains": {"D0": "fs_out"}},
    ],
    chain=(
        "Each example is a pub->tfr->sub chain over gk_logs (LocalFileSrc with "
        "SrcFileFormat.LOG, reading one staged world CSV as LINES: columns `file` + "
        "`message`) / gk_marts (@transformer, calls TableFrame.grok inline and then does "
        "ordinary filter/select/join/sort work on the result) / gk_out (LocalFileDest, "
        "writes each mart as parquet). They assert nothing — they are meant to be READ, "
        "and each file also runs standalone (`python functions/gk_ex_<name>.py`)."
    ),
)

# The S3 EXAMPLES: the examples suite with the storage swapped -- the transformers are
# the SAME objects (gk_s3ex imports them); only the publisher's source and the
# subscriber's destination change, which is the point.
S3_EXAMPLE_LAYOUT = Layout(
    src="gk_logs", ops="gk_marts", sink="gk_out",
    domains=[S3_WORLD_DOMAIN, S3_OUT_DOMAIN],
    collections=[
        {"name": "gk_logs", "type": "s3_file_in",
         "connection_template": "connection-file:connections/s3_file_in.yaml",
         "group": "sources", "domains": {"D0": "s3_world_xs"}},
        {"name": "gk_marts", "type": "transform", "group": "marts"},
        {"name": "gk_out", "type": "s3_file_out",
         "connection_template": "connection-file:connections/s3_file_out.yaml",
         "group": "destinations", "domains": {"D0": "s3_out"}},
    ],
    chain=(
        "Each example is a pub->tfr->sub chain over gk_logs (S3Src with "
        "SrcFileFormat.LOG, globbing the staged world CSVs out of the S3 domain's "
        "bucket prefix) / gk_marts (the SAME transformer objects as the examples "
        "suite, imported by gk_s3ex.py, since a transform collection has no "
        "connection) / gk_out (S3Dest, landing the same parquet names in the S3 out "
        "domain)."
    ),
)

# The S3 TESTS: world_csv with the source swapped -- gk_s3wc imports each case's
# transformer and subscriber and redefines only the publisher on S3Src.
S3_TEST_LAYOUT = Layout(
    src="gk_src", ops="gk_ops", sink="gk_sink",
    domains=[S3_WORLD_DOMAIN, DEV_DOMAIN],
    collections=[
        {"name": "gk_src", "type": "s3_file_in",
         "connection_template": "connection-file:connections/s3_file_in.yaml",
         "group": "sources", "domains": {"D0": "s3_world_xs"}},
        {"name": "gk_ops", "type": "transform", "group": "ops"},
        {"name": "gk_sink", "type": "trash_out",
         "connection_template": "connection-file:connections/trash_out.yaml",
         "group": "destinations", "domains": {"D0": "dev"}},
    ],
    chain=(
        "Every test is a pub->tfr->sub chain over gk_src (S3Src with "
        "SrcFileFormat.LOG, globbing the staged world CSVs out of the S3 domain's "
        "bucket prefix) / gk_ops and gk_sink (the SAME transformer and subscriber "
        "objects as world_csv, imported by gk_s3wc.py -- both are connection-less)."
    ),
)

# category -> (comment, [file stems], layout)
CATEGORIES: dict[str, tuple[str, list[str], Layout]] = {
    "world_csv": (
        "The world model's CSV read back as a LOG (one column per line) and split with "
        "TableFrame.grok: the field split itself, what the ColumnDefinition schema controls "
        "(output name, dtype, column order), the null contract for lines a pattern does not "
        "match, and the messy-line patterns (%{GREEDYDATA}/%{DATA}, quoted fields, an Expr "
        "instead of a column name).",
        ["gk_split", "gk_rename", "gk_types", "gk_nomatch", "gk_country"],
        TEST_LAYOUT,
    ),
    "examples": (
        "TableFrame.grok used the way you would use it in your own project: called inline "
        "in a regular @transformer body, with the parsed result feeding ordinary "
        "filter/select/with_columns/join/sort work and landing as parquet. Covers the basic "
        "line split, a numeric capture plus a second grok over the log's file name, and a "
        "join between two separately parsed logs.",
        ["gk_ex_cities", "gk_ex_langs", "gk_ex_join"],
        EXAMPLE_LAYOUT,
    ),
    "s3_examples": (
        "The examples suite with the storage swapped to S3: the same TableFrame.grok "
        "transformers, but the log lines are read from an S3 domain and the parquet "
        "marts land in one. What changes between local files and an object store is "
        "ONLY the publisher's source and the subscriber's destination.",
        ["gk_s3ex"],
        S3_EXAMPLE_LAYOUT,
    ),
    "s3_world_csv": (
        "The world_csv tests with the storage swapped to S3: the same grok calls and "
        "the same assertions, reading the staged world CSVs from an S3 domain instead "
        "of a local fs one. Only the publishers differ.",
        ["gk_s3wc"],
        S3_TEST_LAYOUT,
    ),
}


def discover(stem: str, layout: Layout):
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
            functions.append({
                "collection": layout.kinds[kind],
                "functionpath": f"functions/{stem}.py::{fname}",
            })
            if kind == "PublisherInfo":
                # The publisher is the only thing to fire: the transformers run on its
                # output table and the subscribers on the transformers'.
                triggers.append({"collection": layout.src, "function": fname,
                                 "detached": True})
    return functions, triggers


def build(comment: str, stems: list[str], layout: Layout) -> dict:
    functions, triggers = [], []
    for stem in stems:
        f, t = discover(stem, layout)
        functions += f
        triggers += t
    return {
        "_comment": f"GROK · {comment} {layout.chain} Generated by gen_suites.py.",
        "domains": layout.domains,
        "collections": layout.collections,
        "functions": functions,
        "triggers": triggers,
    }


def write(path: Path, obj: dict) -> None:
    path.write_text(json.dumps(obj, indent=2) + "\n")
    print(f"wrote {path.relative_to(SUITE)}  ({len(obj['functions'])} fns, "
          f"{len(obj['triggers'])} triggers)")


total_fns = total_trigs = 0
for cat, (comment, stems, layout) in CATEGORIES.items():
    obj = build(comment, stems, layout)
    write(SUITE / f"{cat}.json", obj)
    total_fns += len(obj["functions"])
    total_trigs += len(obj["triggers"])
print(f"\n{len(CATEGORIES)} categor(y|ies), {total_fns} functions, {total_trigs} triggers "
      f"(run all with: tdx-xp oneshot --suite grok)")
