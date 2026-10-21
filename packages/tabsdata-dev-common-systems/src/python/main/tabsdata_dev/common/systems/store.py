#
# Copyright 2026 Tabsdata Inc.
#

"""Resolve a system/domain *name* to its descriptor file path.

Systems and domains are addressed by *name* (a plain identifier), each stored as
a file in the command's data directory: ``<tdd_dir>/data/system`` and
``<tdd_dir>/data/domain`` (see ``common.core.datadir``). An explicit
``--sys-dir`` / ``--domain-dir`` overrides the store directly, and
``$TDD_SYSTEM_DIR`` / ``$TDD_DOMAIN_DIR`` override it when no flag is given --
the way a caller that cannot pass flags (a test harness) points tdd at another
store. ``~`` is expanded; the directory is created by the writer's mkdir on
first use.
"""

from __future__ import annotations

import os
from pathlib import Path

from tabsdata_dev.common.core import datadir
from tabsdata_dev.common.systems import constants


def _store_dir(dir_opt: str | None, env: str, tool: str) -> Path:
    if dir_opt:
        return Path(dir_opt).expanduser()
    elif os.environ.get(env):
        return Path(os.environ[env]).expanduser()
    else:
        return datadir.data_dir(tool)


def system_dir(dir_opt: str | None = None) -> Path:
    return _store_dir(dir_opt, constants.ENV_SYSTEM_DIR, constants.SYS_TOOL)


def domain_dir(dir_opt: str | None = None) -> Path:
    return _store_dir(dir_opt, constants.ENV_DOMAIN_DIR, constants.DOM_TOOL)


def system_path(name: str, dir_opt: str | None = None) -> Path:
    return system_dir(dir_opt) / name


def domain_path(name: str, dir_opt: str | None = None) -> Path:
    return domain_dir(dir_opt) / name
