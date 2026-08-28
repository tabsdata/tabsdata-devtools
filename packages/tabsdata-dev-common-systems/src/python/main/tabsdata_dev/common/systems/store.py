#
# Copyright 2026 Tabsdata Inc.
#

"""Resolve a system/domain *name* to its descriptor file path.

Systems and domains are addressed by *name* (a plain identifier), each stored as
a file in the command's data directory: ``<tdd_dir>/data/system`` and
``<tdd_dir>/data/domain`` (see ``common.core.datadir``). An explicit
``--sys-dir`` / ``--domain-dir`` overrides the store directly. ``~`` is expanded;
the directory is created by the writer's mkdir on first use.
"""

from __future__ import annotations

from pathlib import Path

from tabsdata_dev.common.core import datadir
from tabsdata_dev.common.systems import constants


def system_dir(dir_opt: str | None = None) -> Path:
    return (
        Path(dir_opt).expanduser() if dir_opt else datadir.data_dir(constants.SYS_TOOL)
    )


def domain_dir(dir_opt: str | None = None) -> Path:
    return (
        Path(dir_opt).expanduser() if dir_opt else datadir.data_dir(constants.DOM_TOOL)
    )


def system_path(name: str, dir_opt: str | None = None) -> Path:
    return system_dir(dir_opt) / name


def domain_path(name: str, dir_opt: str | None = None) -> Path:
    return domain_dir(dir_opt) / name
