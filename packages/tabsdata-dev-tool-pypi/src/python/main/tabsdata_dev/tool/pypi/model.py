#
# Copyright 2026 Tabsdata Inc.
#

"""Core data model: a published distribution, and PEP 503 name normalization."""

from __future__ import annotations

import re
from dataclasses import dataclass

_NORMALIZE = re.compile(r"[-_.]+")


def normalize(name: str) -> str:
    """PEP 503 name normalization."""
    return _NORMALIZE.sub("-", name).lower()


@dataclass(frozen=True)
class Dist:
    """One distribution file, as recorded in a tree's root index.json.

    Field order is the JSON key order. Records are read back with ``Dist(**f)``,
    so adding a field is a breaking change for every index already in git unless
    the field has a default.
    """

    filename: str
    release: str
    project: str
    version: str
    sha256: str
    size: int
    requires_python: str | None
    core_metadata_sha256: str | None
    added_at: str
    yanked: str | None = None
