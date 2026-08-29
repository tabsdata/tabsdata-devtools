#
# Copyright 2026 Tabsdata Inc.
#
"""The local pointer store: ``<tdd_dir>/data/xp/``.

``create-instance --suite S --instance I`` records ``i-<I>``: for a definition
file ``{"file": "/abs/path.json"}`` (re-read live on load); for a suite dir one
member pointer per lane (``i-<I>_<name>``) plus a GROUP pointer
``{"group": [members], "suite": "/abs/dir"}``. ``create-project`` records
``p-<P>`` as ``{"instance": "<I>"}`` (or ``{"group": [members]}``), so the later
commands need only ``--project``.
"""

from __future__ import annotations

import json
import pathlib

from tabsdata_dev.common.core import datadir

from . import state, suites
from .models import Instance, build_instance


def store() -> pathlib.Path:
    return datadir.data_dir(state.TOOL)


def instance_file(name: str) -> pathlib.Path:
    return store() / f"i-{name}"


def project_file(project: str) -> pathlib.Path:
    return store() / f"p-{project}"


def _write(path: pathlib.Path, doc: dict) -> None:
    store().mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc) + "\n", encoding="utf-8")


def write_instance(name: str, definition: pathlib.Path) -> None:
    _write(instance_file(name), {"file": str(definition.resolve())})


def write_group_instance(
    name: str, members: list[str], suite_dir: pathlib.Path
) -> None:
    _write(instance_file(name), {"group": members, "suite": str(suite_dir.resolve())})


def write_project(project: str, instance: str) -> None:
    _write(project_file(project), {"instance": instance})


def write_group_project(project: str, members: list[str]) -> None:
    _write(project_file(project), {"group": members})


def doc_of(path: pathlib.Path) -> dict:
    """A pointer as a dict, ``{}`` if missing or malformed -- for labelling."""
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return doc if isinstance(doc, dict) else {}


def load_instance(name: str) -> Instance:
    path = instance_file(name)
    if not path.exists():
        state.die(
            f"instance '{name}' not found ({path}); run `create-instance --suite PATH --instance {name}` first"
        )
    doc = doc_of(path)
    if not doc.get("file"):
        state.die(f'malformed instance pointer {path}: expected {{"file": "<path>"}}')
    return build_instance(name, pathlib.Path(doc["file"]))


def load_project(project: str) -> str:
    """The instance name backing ``project``."""
    path = project_file(project)
    if not path.exists():
        state.die(
            f"project '{project}' not found ({path}); run `create-project --instance INSTANCE --project {project}` first"
        )
    doc = doc_of(path)
    if not doc.get("instance"):
        state.die(
            f'malformed project pointer {path}: expected {{"instance": "<name>"}}'
        )
    return str(doc["instance"])


def _group(path: pathlib.Path) -> list[str] | None:
    doc = doc_of(path)
    return doc.get("group") if isinstance(doc.get("group"), list) else None


def instance_group(name: str) -> list[str] | None:
    return _group(instance_file(name))


def project_group(name: str) -> list[str] | None:
    return _group(project_file(name))


def suite_of_instance(name: str) -> str | None:
    """The suite label behind an instance -- a lane's file or a group's dir.
    This is what labels every progress line."""
    doc = doc_of(instance_file(name))
    ref = doc.get("file") or doc.get("suite")
    return suites.label(pathlib.Path(ref)) if ref else None


def suite_of_project(name: str) -> str | None:
    doc = doc_of(project_file(name))
    if doc.get("group"):
        for member in doc["group"]:
            found = suite_of_project(member)
            if found:
                return found.rsplit("/", 1)[0] if "/" in found else found
        return None
    instance = doc.get("instance")
    return suite_of_instance(instance) if instance else None


def members(prefix: str) -> dict[str, dict | None]:
    """Every ``<prefix><name>`` pointer as ``{name: doc}`` (None = malformed)."""
    out: dict[str, dict | None] = {}
    if not store().is_dir():
        return out
    for path in sorted(store().glob(f"{prefix}*")):
        doc = doc_of(path)
        out[path.name[len(prefix) :]] = doc or None
    return out


def member_of(pointers: dict[str, dict | None]) -> dict[str, str]:
    """group member -> group name."""
    owner: dict[str, str] = {}
    for name, doc in pointers.items():
        if isinstance(doc, dict) and doc.get("group"):
            for m in doc["group"]:
                owner[m] = name
    return owner
