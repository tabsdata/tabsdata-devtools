#
# Copyright 2026 Tabsdata Inc.
#
"""Where suites come from: ``--suite PATH``.

PATH is either a suite definition file (``…/connectors/db2.json``) or a suite
DIRECTORY (``…/suites/connectors``), which fans out to every definition JSON
directly under it -- one instance/project per file (a "swim lane"). The
``connections/`` templates are found by walking up from the suite dir to the
first ancestor holding one (the XP root), so the tool runs from any cwd.
"""

from __future__ import annotations

import json
import pathlib

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


def resolve(spec: str) -> tuple[pathlib.Path, list[pathlib.Path] | None]:
    """``(path, lanes)``: a definition file and ``None``, or a suite dir and its
    lane files. A missing ``.json`` on a file path is tolerated."""
    path = pathlib.Path(spec).expanduser()
    if path.is_dir():
        path = path.resolve()
        lanes = lane_files(path)
        if not lanes:
            state.die(f"no suite definitions (*.json) under {path}")
        return path, lanes
    if path.suffix != ".json" and path.with_name(path.name + ".json").is_file():
        path = path.with_name(path.name + ".json")
    if path.suffix == ".json" and path.is_file():
        return path.resolve(), None
    state.die(f"--suite must be a suite directory or a .json suite file: {spec}")
    raise AssertionError  # unreachable


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
    """The XP root: the nearest ancestor (the suite dir included) holding
    ``connections/``; else the parent of a ``suites/`` ancestor; else the suite
    dir's parent. ``connection-file:`` refs resolve against it."""
    for ancestor in (source_dir, *source_dir.parents):
        if (ancestor / "connections").is_dir():
            return ancestor
    for ancestor in source_dir.parents:
        if ancestor.name == "suites":
            return ancestor.parent
    return source_dir.parent


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
