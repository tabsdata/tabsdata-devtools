#
# Copyright 2026 Tabsdata Inc.
#
"""Offline validator for the ``examples`` suite set.

Four checks, none of which needs a server, a login, the crypto key or any
backend:

1. WIRING — for every ``<name>.json``: each collection names a declared domain
   and (unless it is a connection-less ``transform`` collection) an existing
   connection template; each function names a declared collection and a
   ``functions/<suite>/<file>.py`` that exists and defines that symbol; each
   trigger names a function the suite registers. Pure text/JSON work.

2. LAYOUT — the convention this suite set is built on: ONE DECORATED FUNCTION
   PER FILE, named after the file, in a per-suite directory. A file that defines
   two functions, or one whose name does not match its function, is reported —
   because the whole point of the layout is that a reader can find the example
   for a behaviour by its filename.

3. IMPORT — every function file is imported, which is what runs the
   ``@publisher`` / ``@subscriber`` / ``@transformer`` / ``@stream_publisher``
   DECORATOR VALIDATION: source and destination field types, parameter arity
   against ``output_tables`` / ``input_tables``, ``format_cfg`` side-typing,
   destination path tokens, ``DataQuality`` shapes. Most of the mistakes an
   example can contain surface here, seconds after an edit, instead of at
   ``create-project`` time.

   Files are imported UNDER A UNIQUE MODULE NAME, because the layout puts a
   ``write_append.py`` in a dozen suites and a bare-stem import would collide.
   (The worker does import by bare stem — but with only ONE suite's directory on
   ``sys.path``, so the collision cannot arise there.)

   This step needs a Python that can import ``tabsdatak`` — the EE build, with
   the connector packages INSTALLED (their entry points are what the decorators
   resolve a source/destination class against; having them merely on
   ``PYTHONPATH`` is not enough). Without it the step is SKIPPED, loudly, and
   the other checks still run.

4. OUTPUT-TABLE UNIQUENESS — every table a suite's functions produce must be
   unique WITHIN ITS COLLECTION. ``tdk fn register`` rejects a second function
   that claims a name another already owns ("Tables [x] already exists in
   collection 'y'"), and this reproduces that offline.

What it does NOT check: that a backend exists, that a query is valid SQL, that a
seeded file is where a path says it is, or that a run produces the right rows.
That is what ``tdx-xp oneshot --suite examples/<name>`` is for.

    python suites/examples/validate.py                       # everything
    python suites/examples/validate.py postgres_src_queries  # one suite
    python suites/examples/validate.py --offline             # skip the imports
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
import traceback
from pathlib import Path

SUITE_DIR = Path(__file__).resolve().parent
FN_DIR = SUITE_DIR / "functions"
XP_ROOT = SUITE_DIR.parent.parent          # the dir holding suites/ and connections/

# Collections created WITHOUT a connection (a transformer collection): their
# `group` is neither sources nor destinations and they carry no domains.
_CONNECTIONLESS_GROUPS = {"ops", "marts", "default"}

# The decorators that make a function a flow function.
_DECORATORS = {"publisher", "subscriber", "transformer", "stream_publisher"}


def _functions_in(path: Path) -> list[str]:
    """Top-level function names in `path`, without importing it."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [n.name for n in tree.body if isinstance(n, ast.FunctionDef)]


def _decorated_in(path: Path) -> list[str]:
    """Top-level functions in `path` carrying a flow decorator."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    out = []
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            call = dec.func if isinstance(dec, ast.Call) else dec
            name = getattr(call, "id", None) or getattr(call, "attr", None)
            if name in _DECORATORS:
                out.append(node.name)
                break
    return out


def sections(definition: Path) -> dict[str, list]:
    """A suite's entries by kind, across its stages -- a suite is an ordered
    list of stages, each holding one kind."""
    out: dict[str, list] = {}
    for stage in json.loads(definition.read_text(encoding="utf-8")):
        for kind, value in stage.items():
            if not kind.startswith("_") and isinstance(value, list):
                out.setdefault(kind, []).extend(value)
    return out


def check_wiring(definition: Path) -> list[str]:
    """Problems in one suite definition (empty list = clean)."""
    doc = sections(definition)
    problems: list[str] = []

    # A domains stage is `tdd domain` calls; a domain is declared by its create.
    domains = {d["name"] for d in doc.get("domains", []) if d.get("command") == "create"}
    collections = {c["name"]: c for c in doc.get("collections", [])}

    for name, c in collections.items():
        template = c.get("connection_template")
        if template:
            if not template.startswith("connection-file:"):
                problems.append(f"collection {name}: unsupported template ref {template!r}")
            elif not (XP_ROOT / template.split(":", 1)[1]).exists():
                problems.append(f"collection {name}: missing template {template}")
        elif c.get("group") not in _CONNECTIONLESS_GROUPS:
            problems.append(
                f"collection {name}: no connection_template, but group "
                f"{c.get('group')!r} is not one of {sorted(_CONNECTIONLESS_GROUPS)}"
            )
        for prefix, domain in (c.get("domains") or {}).items():
            if domain not in domains:
                problems.append(f"collection {name}: {prefix} -> undeclared domain {domain!r}")

    registered: set[tuple[str, str]] = set()
    cache: dict[Path, list[str]] = {}
    for f in doc.get("functions", []):
        collection, path = f["collection"], f["functionpath"]
        if collection not in collections:
            problems.append(f"function {path}: undeclared collection {collection!r}")
        file_part, _, symbol = path.partition("::")
        file_path = SUITE_DIR / file_part
        if not file_path.exists():
            problems.append(f"function {path}: no such file {file_part}")
            continue
        if file_path not in cache:
            cache[file_path] = _functions_in(file_path)
        if symbol not in cache[file_path]:
            problems.append(f"function {path}: {file_part} defines no {symbol!r}")
        registered.add((collection, symbol))

    for t in doc.get("triggers", []):
        key = (t["collection"], t["function"])
        if key not in registered:
            problems.append(
                f"trigger {key[0]}/{key[1]}: not registered by this suite's functions"
            )
    return problems


def check_layout(suite: str) -> list[str]:
    """ONE DECORATED FUNCTION PER FILE, named after the file.

    The suite set's whole navigational premise is that `functions/<suite>/` lists
    the behaviours and each filename IS the example's name. A file with two
    functions in it, or one whose function is called something else, breaks that
    silently — nothing fails, the examples just stop being findable.
    """
    d = FN_DIR / suite
    problems: list[str] = []
    if not d.is_dir():
        return [f"no functions/{suite}/ directory"]
    for path in sorted(d.glob("*.py")):
        decorated = _decorated_in(path)
        if len(decorated) != 1:
            problems.append(
                f"{path.name}: expected exactly ONE decorated function, found "
                f"{len(decorated)}{' (' + ', '.join(decorated) + ')' if decorated else ''}"
            )
            continue
        expected = path.stem.removeprefix("supporting_")
        if decorated[0] != expected:
            problems.append(
                f"{path.name}: defines {decorated[0]!r}, expected {expected!r} "
                f"(the file is named after its function)"
            )
    return problems


def _import(path: Path, unique_name: str):
    """Import `path` under a unique module name, so same-named files in different
    suite directories cannot collide in one interpreter."""
    spec = importlib.util.spec_from_file_location(unique_name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[unique_name] = module
    spec.loader.exec_module(module)
    return module


def _derived_tables(info) -> list[str]:
    """The extra tables a function's `on_tables` data-quality actions register in
    the collection: an operator's explicit `to_table` / `table`, or the implicit
    ``<target>_dq_summary`` a bare ``Summary()`` produces."""
    tables: list[str] = []
    for action in getattr(info, "on_tables", None) or []:
        target = getattr(action, "table", None)
        for op in getattr(action, "operators", None) or []:
            named = getattr(op, "to_table", None) or getattr(op, "table", None)
            if named:
                tables.append(named)
            elif type(op).__name__ == "Summary" and target:
                tables.append(f"{target}_dq_summary")
    return tables


def check_table_names(definition: Path, modules: dict) -> list[str]:
    """Every table a suite produces must be unique within its COLLECTION.

    Needs the imported modules: `output_tables` lives on the decorated object,
    not in the JSON.
    """
    doc = sections(definition)
    problems: list[str] = []
    owner: dict[tuple[str, str], str] = {}

    for f in doc.get("functions", []):
        collection, path = f["collection"], f["functionpath"]
        file_part, _, symbol = path.partition("::")
        module = modules.get(file_part)
        if module is None:
            continue                      # its import already failed and was reported
        info = getattr(module, symbol, None)
        if info is None:
            continue                      # the wiring check already reported this
        produced = list(getattr(info, "output_tables", None) or [])
        produced += _derived_tables(info)
        for table in produced:
            key = (collection, table)
            if key in owner:
                problems.append(
                    f"collection {collection!r}: table {table!r} is claimed by both "
                    f"{owner[key]} and {symbol}"
                )
            else:
                owner[key] = symbol
    return problems


def _report(title: str, results: dict[str, list[str]]) -> int:
    print(f"\n== {title} ==")
    failures = 0
    for name, problems in sorted(results.items()):
        if problems:
            failures += 1
            print(f"FAIL  {name}")
            for p in problems:
                print(f"        {p}")
        else:
            print(f"OK    {name}")
    return failures


def main() -> int:
    argv = sys.argv[1:]
    offline = "--offline" in argv
    wanted = [a[:-5] if a.endswith(".json") else a for a in argv if not a.startswith("-")]
    definitions = (
        [SUITE_DIR / f"{w}.json" for w in wanted]
        if wanted
        else sorted(SUITE_DIR.glob("*.json"))
    )

    missing = [d for d in definitions if not d.exists()]
    for d in missing:
        print(f"FAIL  {d.name}: no such suite definition")
    definitions = [d for d in definitions if d.exists()]

    failures = len(missing)
    print(f"== wiring ({len(definitions)} suite definition(s)) ==")
    for definition in definitions:
        problems = check_wiring(definition)
        if problems:
            failures += 1
            print(f"FAIL  {definition.stem}")
            for p in problems:
                print(f"        {p}")
        else:
            print(f"OK    {definition.stem}")

    failures += _report(
        "layout (one decorated function per file, named after it)",
        {d.stem: check_layout(d.stem) for d in definitions},
    )

    if offline:
        return 1 if failures else 0

    print("\n== import / decorator validation ==")
    try:
        importlib.import_module("tabsdatak.api")
    except Exception as e:  # noqa: BLE001 -- any import failure means "not the EE build"
        print(f"SKIP  tabsdatak is not importable here ({type(e).__name__}: {e}).")
        print("      Run this with the EE venv, with the connector packages installed.")
        return 1 if failures else 0

    modules: dict[str, object] = {}
    for definition in definitions:
        suite = definition.stem
        for path in sorted((FN_DIR / suite).glob("*.py")):
            rel = f"functions/{suite}/{path.name}"
            try:
                modules[rel] = _import(path, f"examples_{suite}_{path.stem}")
            except Exception as e:  # noqa: BLE001 -- report and carry on
                failures += 1
                print(f"FAIL  {rel}: {type(e).__name__}: {e}")
                traceback.print_exc()
    print(f"OK    imported {len(modules)} function file(s)")

    failures += _report(
        "output-table uniqueness",
        {d.stem: check_table_names(d, modules) for d in definitions},
    )
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
