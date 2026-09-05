#
# Copyright 2026 Tabsdata Inc.
#

"""gsx's version, which is the devtools version.

Every package takes its version from the repo's ``VERSION`` file (invariant
10), so the installed distribution's metadata is that number -- there is no
second version to keep in step. Outside an install (a bare pytest run of the
source tree) the metadata is absent and the tdd dir's stamp answers instead.
"""

from __future__ import annotations

import importlib.metadata

from tabsdata_dev.common.core import datadir

DIST = "tabsdata-dev-tool-gsx"


def _version() -> str:
    try:
        return importlib.metadata.version(DIST)
    except importlib.metadata.PackageNotFoundError:
        pass
    try:
        return (datadir.tdd_dir() / "VERSION").read_text(encoding="utf-8").strip()
    except OSError:
        return "0"


VERSION = _version()
