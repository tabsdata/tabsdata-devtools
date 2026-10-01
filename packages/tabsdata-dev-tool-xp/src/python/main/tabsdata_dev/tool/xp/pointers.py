#
# Copyright 2026 Tabsdata Inc.
#
"""The local pointer store: ``<tdd_dir>/data/xp/``.

``create-instance --suite S --suite-run R`` records the suite run ``i-<R>``:
for a definition file ``{"file": "/abs/path.json", "xp_id", "xp_short_id"}``
(the suite re-read live on load, for the run its IDs name); for a suite dir one
member pointer per lane (``i-<R>_<name>``, each a run with IDs of its own)
plus a GROUP pointer ``{"group": [members], "suite": "/abs/dir", "xp_id",
"xp_short_id"}``. R defaults to the run's XP_ID, so a suite run is always a
file holding its XP_ID. ``create-project`` records ``p-<P>`` as
``{"instance": "<R>"}`` (or ``{"group": [members]}``), so the later commands
need only ``--project``.
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


def write_instance(name: str, definition: pathlib.Path, ids_: tuple[str, str]) -> None:
    _write(
        instance_file(name),
        {"file": str(definition.resolve()), "xp_id": ids_[0], "xp_short_id": ids_[1]},
    )


def write_group_instance(
    name: str, members: list[str], suite_dir: pathlib.Path, ids_: tuple[str, str]
) -> None:
    _write(
        instance_file(name),
        {
            "group": members,
            "suite": str(suite_dir.resolve()),
            "xp_id": ids_[0],
            "xp_short_id": ids_[1],
        },
    )


def ids_of(name: str) -> tuple[str, str] | None:
    """The ``(XP_ID, XP_SHORT_ID)`` a suite run's pointer holds, if it holds them."""
    doc = doc_of(instance_file(name))
    if doc.get("xp_id") and doc.get("xp_short_id"):
        return str(doc["xp_id"]), str(doc["xp_short_id"])
    return None


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
            f"suite run '{name}' not found ({path}); run `create-instance --suite PATH --suite-run {name}` first"
        )
    doc = doc_of(path)
    if not doc.get("file"):
        state.die(f'malformed suite run pointer {path}: expected {{"file": "<path>"}}')
    if not (doc.get("xp_id") and doc.get("xp_short_id")):
        state.die(
            f"suite run pointer {path} holds no XP_ID (an older xp wrote it): "
            f"`destroy-instance --suite-run {name}`, then create it again"
        )
    return build_instance(
        name, pathlib.Path(doc["file"]), doc["xp_id"], doc["xp_short_id"]
    )


def load_project(project: str) -> str:
    """The instance name backing ``project``."""
    path = project_file(project)
    if not path.exists():
        state.die(
            f"project '{project}' not found ({path}); run `create-project --suite-run R --project {project}` first"
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
