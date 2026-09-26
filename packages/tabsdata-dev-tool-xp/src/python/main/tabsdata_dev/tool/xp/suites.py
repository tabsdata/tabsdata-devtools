#
# Copyright 2026 Tabsdata Inc.
#
"""Where suites come from: ``--suite SELECTOR`` under a suites directory.

The suites are carried BY this package -- ``xp-tool/suites/`` and
``xp-tool/connections/`` are tabsdata-xp's trees, copied verbatim -- and are the
default; ``--suites-dir DIR`` looks a selector up there instead
(``export-suites --dir`` writes a copy to edit). They live at the repo root and
a wheel build copies them in beside this module; see `builtin_root()`. A
selector is ``<type>/<name>`` (``.json`` optional) for one definition, or
``<type>`` for a suite DIRECTORY, which fans out to every definition JSON
directly under it -- one instance/project per file (a "swim lane"). An explicit
path to a file or dir still works when no selector matches. The
``connections/`` templates are found by walking up from the suite dir to the
first ancestor holding one (the XP root), else the built-in ones are used.
"""

from __future__ import annotations

import json
import pathlib
import shutil
from importlib.resources import files

from . import state

SECTIONS = {"domains", "collections", "functions", "triggers", "monitor", "live"}


def is_suite_def(path: pathlib.Path) -> bool:
    """True if ``path`` is a suite-definition JSON -- a list of stages, or the
    older single object, carrying at least one suite section -- rather than
    some other JSON living in the dir."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return False
    if isinstance(doc, dict):
        return bool(SECTIONS & doc.keys())
    return isinstance(doc, list) and any(
        isinstance(e, dict) and SECTIONS & e.keys() for e in doc
    )


def lane_files(directory: pathlib.Path) -> list[pathlib.Path]:
    return [p for p in sorted(directory.glob("*.json")) if is_suite_def(p)]


#: The checkout keeps the XP tree here, at the repo root, where it is read and
#: edited; a wheel build copies it in beside this module (force-include). One
#: name in both layouts, so nothing has to say which is which.
TREE_DIR = "xp-tool"


def builtin_root() -> pathlib.Path:
    """The XP tree this package carries: ``suites/`` and ``connections/``.

    A wheel install has it beside this module. An editable install copies
    nothing -- a link has no build step to hook -- so there it is still at the
    repo root, which is where the suites are meant to be read and edited anyway.
    Both layouts are normal; probe for ``suites/`` to tell them apart.
    """
    here = pathlib.Path(str(files("tabsdata_dev.tool.xp")))
    beside = here / TREE_DIR
    if (beside / "suites").is_dir():
        return beside
    # .../packages/<pkg>/src/python/main/tabsdata_dev/tool/xp -> the repo
    repo = here.parents[7] / TREE_DIR
    if (repo / "suites").is_dir():
        return repo
    raise FileNotFoundError(f"xp suites not found beside {beside} nor at {repo}")


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
    ``container-connectors/db2``, ``container-connectors/db2.json`` or
    ``container-connectors`` -- and, when
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
        f"suite {spec!r} not found under {root} (as <type>/<name>, "
        f"<type>/<name>.json or <type>) nor as a path" + _did_you_mean(root, spec)
    )


def _did_you_mean(root: pathlib.Path, spec: str) -> str:
    """The suites a mistyped selector was probably reaching for.

    A selector is `<type>/<name>` and the name alone is what a reader remembers
    -- `--suite s3` for `cloud-connectors/s3`, which is exactly the shape that
    stopped working when the connectors were split in two. Naming the candidate
    turns a second round trip into a correction, and it is offered rather than
    accepted: a bare name is unique today and need not stay so, so resolving it
    silently would one day pick a suite nobody asked for.
    """
    try:
        every = [row["suite"] for row in list_suites(root)]
    except OSError:
        return "; `list-suites` shows what is there"
    wanted = spec.strip("/").lower()
    leaf = [s for s in every if pathlib.PurePath(s).name.lower() == wanted]
    near = leaf or [s for s in every if wanted and wanted in s.lower()]
    if not near:
        return "; `list-suites` shows what is there"
    if len(near) == 1:
        return f"; did you mean {near[0]}?"
    shown = ", ".join(near[:6]) + (" ..." if len(near) > 6 else "")
    return f"; did you mean one of {shown}?"
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
