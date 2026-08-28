#
# Copyright 2026 Tabsdata Inc.
#

"""Where a command keeps persistent state: ``<tdd_dir>/data/<command>/``.

The tdd dir is the one location every tool already knows (``$TDD_DIR``, set by
the dispatcher before exec; ``~/.tdd`` otherwise), so a command's data lives
beside the envs and travels with the dir. Nothing is created here -- the writer
makes the directory when it first has something to put in it.
"""

from __future__ import annotations

import os
import pathlib


def tdd_dir() -> pathlib.Path:
    return pathlib.Path(os.environ.get("TDD_DIR") or (pathlib.Path.home() / ".tdd"))


def data_dir(command: str) -> pathlib.Path:
    """``<tdd_dir>/data/<command>`` -- the command's own state directory."""
    return tdd_dir() / "data" / command
