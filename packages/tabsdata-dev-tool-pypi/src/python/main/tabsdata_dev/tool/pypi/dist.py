#
# Copyright 2026 Tabsdata Inc.
#

"""Read a wheel: its sha256, its core metadata, and the fields the index needs."""

from __future__ import annotations

import hashlib
import zipfile
from datetime import UTC, datetime
from email.parser import BytesParser
from pathlib import Path

from tabsdata_dev.common.core.errors import ToolError

from .model import Dist, normalize


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def core_metadata(path: Path) -> bytes:
    """Raw METADATA bytes from the wheel's top-level .dist-info directory."""
    with zipfile.ZipFile(path) as zf:
        names = [
            n
            for n in zf.namelist()
            if n.endswith(".dist-info/METADATA") and n.count("/") == 1
        ]
        if len(names) != 1:
            raise ToolError(
                f"{path.name}: expected exactly one top-level METADATA, got {names}"
            )
        return zf.read(names[0])


def describe(path: Path, release: str) -> tuple[Dist, bytes]:
    """-> (index record, raw METADATA bytes).

    The project name comes from METADATA rather than from parsing the filename,
    which is ambiguous for names containing separators.
    """
    raw = core_metadata(path)
    meta = BytesParser().parsebytes(raw)
    name = meta["Name"]
    version = meta["Version"]
    if not name or not version:
        raise ToolError(f"{path.name}: METADATA is missing Name or Version")

    dist = Dist(
        filename=path.name,
        release=release,
        project=normalize(name),
        version=version,
        sha256=sha256_file(path),
        size=path.stat().st_size,
        requires_python=meta.get("Requires-Python"),
        core_metadata_sha256=hashlib.sha256(raw).hexdigest(),
        added_at=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    return dist, raw
