#
# Copyright 2026 Tabsdata Inc.
#
"""Where suites come from: ``--suite SELECTOR`` under a suites directory.

The suites ship INSIDE this package -- ``xp/suites/`` and ``xp/connections/``
are tabsdata-xp's trees, copied verbatim -- and are the default; ``--suites-dir
DIR`` looks a selector up there instead (``export-suites --dir`` writes a copy
to edit). A selector is ``<type>/<name>`` (``.json`` optional) for one
definition, or ``<type>`` for a suite DIRECTORY, which fans out to every
definition JSON directly under it -- one instance/project per file (a "swim
lane"). An explicit path to a file or dir still works when no selector matches.
The ``connections/`` templates are found by walking up from the suite dir to the
first ancestor holding one (the XP root), else the built-in ones are used.
"""

from __future__ import annotations

import json
import pathlib
import shutil
from importlib.resources import files

from . import state

SECTIONS = {"domains", "collections", "functions", "triggers"}


def is_suite_def(path: pathlib.Path) -> bool:
    """True if ``path`` is a suite-definition JSON (a dict carrying at least one
    suite section) rather than some other JSON living in the dir."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    return isinstance(doc, dict) and bool(SECTIONS & doc.keys())


def lane_files(directory: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in sorted(directory.glob("*.json")) if is_suite_def(p)]


def builtin_root() -> pathlib.Path:
    """The XP tree this package ships: ``suites/`` and ``connections/``."""
    return pathlib.Path(str(files("tabsdata_dev.tool.xp_run").joinpath("xp")))


def suites_dir(override: str | None) -> pathlib.Path:
    """The directory selectors are looked up in: --suites-dir, else built-in."""
    if not override:
        return builtin_root() / "suites"
    path = pathlib.Path(override).expanduser()
    if not path.is_dir():
        state.die(f"--suites-dir is not a directory: {path}")
    return path.resolve()


def resolve(
    spec: str, suites_root: pathlib.Path | None = None
) -> tuple[pathlib.Path, list[pathlib.Path] | None]:
    """``(path, lanes)``: a definition file and ``None``, or a suite dir and its
    lane files. `spec` is looked up under `suites_root` (built-in by default) --
    ``connectors/db2``, ``connectors/db2.json`` or ``connectors`` -- and, when
    nothing there matches, taken as a path of its own."""
    root = suites_root if suites_root is not None else builtin_root() / "suites"
    sel = spec.strip().strip("/")
    candidates = [root / sel, root / f"{sel}.json"]
    own = pathlib.Path(spec).expanduser()
    candidates += (
        [own, own.with_name(own.name + ".json")] if own.suffix != ".json" else [own]
    )
    for path in candidates:
        if path.is_dir():
            path = path.resolve()
            lanes = lane_files(path)
            if not lanes:
                state.die(f"no suite definitions (*.json) under {path}")
            return path, lanes
        if path.suffix == ".json" and path.is_file():
            return path.resolve(), None
    state.die(
        f"suite {spec!r} not found under {root} (as <type>/<name>, <type>/<name>.json or <type>) nor as a path; `list-suites` shows what is there"
    )
    raise AssertionError  # unreachable


def export(dest: pathlib.Path, force: bool) -> dict:
    """Copy the built-in ``suites/`` and ``connections/`` under `dest`."""
    root = builtin_root()
    dest = dest.expanduser().resolve()
    out: dict = {"dir": str(dest)}
    for name in ("suites", "connections"):
        target = dest / name
        if target.exists() and not force:
            state.die(f"{target} exists; --force overwrites it")
        shutil.copytree(
            root / name,
            target,
            dirs_exist_ok=force,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
        )
        out[name] = sum(1 for p in target.rglob("*") if p.is_file())
    return out


def label(path: pathlib.Path) -> str:
    """What names the suite on every progress line: ``<type>/<name>`` for a
    file, the dir name for a dir."""
    path = pathlib.Path(path)
    return (
        path.name
        if path.is_dir() or path.suffix != ".json"
        else f"{path.parent.name}/{path.stem}"
    )


def token(path: pathlib.Path) -> str:
    """The short label for oneshot/bench names: ``<type>_<name>`` (a trailing
    ``suite`` file name is dropped: ``medallion/suite`` -> ``medallion``)."""
    path = pathlib.Path(path)
    if path.is_dir() or path.suffix != ".json":
        return _ident(path.name)
    if path.stem == "suite":
        return _ident(path.parent.name)
    return _ident(f"{path.parent.name}_{path.stem}")


def _ident(text: str) -> str:
    import re

    return re.sub(r"[^A-Za-z0-9_]+", "_", text).strip("_") or "suite"


def base_dir(source_dir: pathlib.Path) -> pathlib.Path:
    """The XP root ``connection-file:`` refs resolve against: the nearest
    ancestor (the suite dir included) holding ``connections/``, else the
    built-in root -- so a --suites-dir with definitions only still finds the
    shipped templates."""
    for ancestor in (source_dir, *source_dir.parents):
        if (ancestor / "connections").is_dir():
            return ancestor
    return builtin_root()


def list_suites(root: pathlib.Path) -> list[dict]:
    """Every definition under `root`, recursively, with its section counts."""
    rows = []
    for path in sorted(root.rglob("*.json")):
        parts = path.relative_to(root).parts
        if "functions" in parts or "__pycache__" in parts or not is_suite_def(path):
            continue
        doc = json.loads(path.read_text(encoding="utf-8"))
        rows.append(
            {
                "suite": str(path.relative_to(root).with_suffix("")),
                "path": str(path),
                "domains": len(doc.get("domains", [])),
                "collections": len(doc.get("collections", [])),
                "functions": len(doc.get("functions", [])),
                "triggers": len(doc.get("triggers", [])),
            }
        )
    return rows
