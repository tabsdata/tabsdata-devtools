#
# Copyright 2026 Tabsdata Inc.
#

"""The managed venvs of `tdd venv`, seen from a Python tool.

`tdd venv` keeps them under ``<tdd_dir>/managed-venvs/<manager>/<name>`` with a
``<name>.env`` marker beside the manager directories holding the manager
(pyenv, uv or conda), and exports ``_TDD_VENV=<name>`` while one is active. A
tool that must run *inside* the user's venv rather than its own toolset --
the tdk launchers -- resolves that here and gets the argv that runs a program
in it through the venv's manager, keeping the caller's cwd.
"""

from __future__ import annotations

import os
import pathlib

from . import datadir
from .errors import ToolError

ENV_ACTIVE = "_TDD_VENV"
MARKER_SUFFIX = ".env"
MANAGERS = ("pyenv", "uv", "conda")


def root() -> pathlib.Path:
    return datadir.tdd_dir() / "managed-venvs"


def active() -> str:
    """The name in $_TDD_VENV, else the managed venv the environment says is
    active (see `adopted`), else a ToolError saying how to get one."""
    name = os.environ.get(ENV_ACTIVE, "").strip() or adopted()
    if not name:
        raise ToolError(
            f"no managed venv is active ({ENV_ACTIVE} is unset); a venv activated with "
            "`tdd venv` is required: tdd venv activate --name NAME, or tdd venv create"
        )
    return name


def adopted() -> str | None:
    """The managed venv active in the environment without tdd's record -- a
    shell that entered it before a reinstall renamed the record, `source
    bin/activate` by hand, a script. All three managers leave a path (uv and
    pyenv venvs in VIRTUAL_ENV, conda in CONDA_PREFIX; conda's base is not a
    venv); it is ours when it is exactly ``<root>/<manager>/<name>`` and the
    marker agrees. Mirrors `_tdd_venv_adopt` in venv.sh."""
    path = os.environ.get("VIRTUAL_ENV", "").strip()
    if not path:
        conda = os.environ.get("CONDA_PREFIX", "").strip()
        if conda and os.environ.get("CONDA_DEFAULT_ENV", "base") != "base":
            path = conda
    if not path:
        return None
    try:
        rel = pathlib.Path(path).resolve().relative_to(root().resolve())
    except (ValueError, OSError):
        return None
    if len(rel.parts) != 2:
        return None
    manager, name = rel.parts
    marker = root() / f"{name}{MARKER_SUFFIX}"
    if manager not in MANAGERS or not marker.is_file():
        return None
    if marker.read_text().strip() != manager:
        return None
    return name


def resolve(name: str) -> tuple[str, pathlib.Path]:
    """(manager, directory) of the managed venv `name`, from its marker."""
    marker = root() / f"{name}{MARKER_SUFFIX}"
    if not marker.is_file():
        raise ToolError(
            f"{ENV_ACTIVE}={name} but {marker} does not exist; `tdd venv list` shows "
            "the managed venvs"
        )
    manager = marker.read_text().strip()
    if manager not in MANAGERS:
        raise ToolError(f"{marker} names an unknown venv manager {manager!r}")
    path = root() / manager / name
    if not path.is_dir():
        raise ToolError(
            f"{name} ({manager}) has lost its directory {path}; "
            "delete and recreate it with tdd venv"
        )
    return manager, path


def launch(
    manager: str, path: pathlib.Path, cmd: str, args: list[str]
) -> tuple[list[str], dict[str, str]]:
    """argv, and the variables to add to the environment, that run `cmd args`
    inside the venv through its manager without changing the cwd.

    uv: `uv run --active` takes the venv from $VIRTUAL_ENV; `--no-project`
    keeps it from adopting whatever pyproject.toml the cwd happens to hold
    (`--project DIR` wants a project, not a bare venv, and silently falls
    through to another interpreter when given one). conda: `conda run -p`;
    without --no-capture-output it buffers the child's output until exit,
    useless for a server. pyenv: the venv is a plain `python -m venv` built
    from a pyenv interpreter, outside ~/.pyenv/versions, so `pyenv exec`
    cannot see it -- its own bin/, put first on PATH like activation does, is
    the exact equivalent.
    """
    if manager == "uv":
        return ["uv", "run", "--active", "--no-project", cmd, *args], {
            "VIRTUAL_ENV": str(path)
        }
    if manager == "conda":
        return [
            "conda",
            "run",
            "--prefix",
            str(path),
            "--no-capture-output",
            cmd,
            *args,
        ], {}
    # What activation would do, so a program spawning `python` by name gets the
    # venv's rather than the launcher toolset's, which the dispatcher put first.
    return [str(path / "bin" / cmd), *args], {
        "VIRTUAL_ENV": str(path),
        "PATH": str(path / "bin") + os.pathsep + os.environ.get("PATH", ""),
    }
