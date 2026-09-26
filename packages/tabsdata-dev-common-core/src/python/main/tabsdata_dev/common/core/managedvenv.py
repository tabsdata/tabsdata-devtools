#
# Copyright 2026 Tabsdata Inc.
#

"""The managed venvs of `tdd venv`, seen from a Python tool.

`tdd venv` keeps them under ``<tdd_dir>/managed-venvs/<manager>/<name>`` with a
``<name>.json`` marker beside the manager directories: the manager (pyenv, uv
or conda) under ``manager``, and what the venv is -- ``python`` (the version
it runs), ``python_path`` (the base interpreter it was built from),
``relocatable``, ``created`` -- and exports ``_TDD_VENV=<name>`` while one is
active. A tool that must run *inside* the user's venv rather than its own
toolset -- the tdk launchers, mexe -- asks `select` which venv that is and gets
the argv that runs a program in it, keeping the caller's cwd.

**The venv last activated wins** (`select`), managed or not. `tdd venv
activate` really activates, so the venv the environment has active --
``VIRTUAL_ENV``, else a conda env other than base -- is always the latest one:
the managed venv tdd entered, or one entered on top of it by hand. The dispatcher
passes both variables through untouched, so every nested `tdd` call sees the
shell's. The exception is ``_TDD_VENV`` set by hand, inline (``_TDD_VENV=X tdd
tdk``) or exported: that is later still. `tdd venv` exports the name it
activated a second time, in ``_TDD_VENV_ACTIVATED``, and a ``_TDD_VENV`` that
differs from it was not set by `tdd venv` -- so it wins; one that matches is only
the record, and yields to the shell's venv. A shell from before that second
variable has none, so its ``_TDD_VENV`` still wins, as it always did.

Layouts are asked of the venv, never of the platform (as ``tddsrc.ps1`` does):
executables live in ``bin/`` on Unix and ``Scripts\\`` on Windows, a program is
``tdk`` or ``tdk.exe``, and a Windows conda env also keeps DLLs and tools in
its root and ``Library\\bin``.

The marker used to be ``<name>.env`` holding the manager alone; `tdd venv`
migrates one on sight, so this side reads JSON only and names the fix when it
meets the old file.
"""

from __future__ import annotations

import dataclasses
import json
import os
import pathlib
from typing import Any

from . import datadir
from .errors import ToolError

ENV_ACTIVE = "_TDD_VENV"
ENV_ACTIVATED = "_TDD_VENV_ACTIVATED"
MARKER_SUFFIX = ".json"
LEGACY_MARKER_SUFFIX = ".env"
MANAGERS = ("pyenv", "uv", "conda")


def root() -> pathlib.Path:
    return datadir.tdd_dir() / "managed-venvs"


def marker_path(name: str) -> pathlib.Path:
    return root() / f"{name}{MARKER_SUFFIX}"


def marker(name: str) -> dict[str, Any] | None:
    """What the marker of `name` records, or None when there is none or it is
    not a JSON object naming a manager."""
    path = marker_path(name)
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or not isinstance(data.get("manager"), str):
        return None
    return data


@dataclasses.dataclass(frozen=True)
class Venv:
    """The venv a program is to run in, and why it is that one.

    `name` is set for a managed venv (`manager` is then pyenv, uv or conda);
    a venv tdd does not manage has no name and `manager` says what it is,
    ``venv`` or ``conda``."""

    path: pathlib.Path
    manager: str
    name: str | None
    why: str

    def describe(self) -> str:
        if self.name:
            return f"managed venv {self.name} ({self.manager}, {self.path})"
        return f"venv {self.path} ({self.manager}, not managed by tdd)"


def select(required: bool = True) -> Venv | None:
    """The venv last activated (see the module docstring): a hand-set
    ``_TDD_VENV``, else the venv active in the environment, else the one
    ``_TDD_VENV`` records -- the shell has left it by hand since. None, or a
    ToolError saying how to get one, when there is none."""
    name = os.environ.get(ENV_ACTIVE, "").strip()
    if name and name != os.environ.get(ENV_ACTIVATED, "").strip():
        return _managed(name, f"{ENV_ACTIVE}={name}, set by hand")
    here, kind = _shell()
    if here is not None:
        found = managed_name(here)
        if found:
            return _managed(found, "the venv active in the shell")
        return Venv(here, kind, None, "the venv active in the shell")
    if name:
        return _managed(
            name,
            f"{ENV_ACTIVE}={name} (tdd venv's record; no venv active in the shell)",
        )
    if not required:
        return None
    raise ToolError(
        "no venv is active: activate one that has the program installed -- any venv, "
        "or a managed one with tdd venv activate --name NAME (tdd venv create makes "
        f"one) -- or name a managed one with {ENV_ACTIVE}=NAME"
    )


def _managed(name: str, why: str) -> Venv:
    manager, path = resolve(name)
    return Venv(path, manager, name, why)


def shell_venv() -> pathlib.Path | None:
    """The venv the environment has active (see `_shell`)."""
    return _shell()[0]


def _shell() -> tuple[pathlib.Path | None, str]:
    """(path, venv|conda) of the venv the environment has active: all three
    managers leave a path (uv and pyenv venvs, and any plain venv, in
    VIRTUAL_ENV; conda in CONDA_PREFIX). conda's base is not a venv -- it is
    what a conda install leaves active in every shell."""
    path = os.environ.get("VIRTUAL_ENV", "").strip()
    if path:
        return pathlib.Path(path), "venv"
    conda = os.environ.get("CONDA_PREFIX", "").strip()
    if conda and os.environ.get("CONDA_DEFAULT_ENV", "base") != "base":
        return pathlib.Path(conda), "conda"
    return None, "venv"


def adopted() -> str | None:
    """The managed venv active in the environment without tdd's record -- a
    shell that entered it before a reinstall renamed the record, `source
    bin/activate` by hand, a script. Mirrors `_tdd_venv_adopt` in venv.sh."""
    here = shell_venv()
    return managed_name(here) if here is not None else None


def managed_name(path: pathlib.Path) -> str | None:
    """The managed venv at `path`: ours when it is exactly
    ``<root>/<manager>/<name>`` and the marker agrees."""
    try:
        rel = path.resolve().relative_to(root().resolve())
    except (ValueError, OSError):
        return None
    if len(rel.parts) != 2:
        return None
    manager, name = rel.parts
    if manager not in MANAGERS:
        return None
    data = marker(name)
    if data is None or data["manager"] != manager:
        return None
    return name


def resolve(name: str) -> tuple[str, pathlib.Path]:
    """(manager, directory) of the managed venv `name`, from its marker."""
    path = marker_path(name)
    data = marker(name)
    if data is None:
        if (root() / f"{name}{LEGACY_MARKER_SUFFIX}").is_file():
            # From before the JSON marker: `tdd venv` rewrites it on sight.
            raise ToolError(
                f"{ENV_ACTIVE}={name} has a marker from an older tdd "
                f"({name}{LEGACY_MARKER_SUFFIX}); run `tdd venv list` once to "
                "migrate it"
            )
        if path.is_file():
            raise ToolError(
                f"{path} is not a managed venv marker (JSON naming a manager)"
            )
        raise ToolError(
            f"{ENV_ACTIVE}={name} but {path} does not exist; `tdd venv list` shows "
            "the managed venvs"
        )
    manager = data["manager"]
    if manager not in MANAGERS:
        raise ToolError(f"{path} names an unknown venv manager {manager!r}")
    path = root() / manager / name
    if not path.is_dir():
        raise ToolError(
            f"{name} ({manager}) has lost its directory {path}; "
            "delete and recreate it with tdd venv"
        )
    return manager, path


def bin_dir(prefix: pathlib.Path) -> pathlib.Path:
    """Where the venv keeps its executables: ``bin/``, or ``Scripts\\`` for one
    built on Windows (the twin of ``_tdd_venv_bin`` in tddsrc.ps1)."""
    for leaf in ("bin", "Scripts"):
        if (prefix / leaf).is_dir():
            return prefix / leaf
    return prefix / "bin"


def program(prefix: pathlib.Path, cmd: str) -> pathlib.Path | None:
    """`cmd` inside the venv, with or without ``.exe``, or None."""
    for suffix in ("", ".exe"):
        candidate = bin_dir(prefix) / f"{cmd}{suffix}"
        if candidate.is_file():
            return candidate
    return None


def path_dirs(prefix: pathlib.Path, manager: str) -> list[pathlib.Path]:
    """The directories activating the venv puts first on PATH. A conda env
    built on Windows adds its root (python.exe) and ``Library\\bin`` (its
    DLLs) to ``Scripts\\``."""
    bin_ = bin_dir(prefix)
    if manager == "conda" and bin_.name == "Scripts":
        return [prefix, bin_, prefix / "Library" / "bin"]
    return [bin_]


def _first_on_path(dirs: list[pathlib.Path]) -> str:
    first = [str(d) for d in dirs]
    rest = [p for p in os.environ.get("PATH", "").split(os.pathsep) if p not in first]
    return os.pathsep.join(first + rest)


def launch_in(
    venv: Venv, cmd: str, args: list[str]
) -> tuple[list[str], dict[str, str]]:
    """argv and the variables to add that run `cmd args` in `venv`. A managed
    venv goes through its manager (`launch`). One tdd does not manage is active
    in the calling shell by construction, so whatever activating it set up is
    already in the environment: the program by path with its directories first
    on PATH is the whole of it."""
    if venv.name:
        return launch(venv.manager, venv.path, cmd, args)
    prog = program(venv.path, cmd) or bin_dir(venv.path) / cmd
    key = "CONDA_PREFIX" if venv.manager == "conda" else "VIRTUAL_ENV"
    return [str(prog), *args], {
        key: str(venv.path),
        "PATH": _first_on_path(path_dirs(venv.path, venv.manager)),
    }


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
        # The program by path, and the venv's bin/ first: `conda run` prepends
        # it only when the env is not already active -- in a shell where it is,
        # the existing entry is updated in place, behind the toolset bin/ the
        # dispatcher put first, and a bare `tdk` resolved to this launcher again,
        # which ran `conda run` again, without end.
        return [
            "conda",
            "run",
            "--prefix",
            str(path),
            "--no-capture-output",
            str(program(path, cmd) or bin_dir(path) / cmd),
            *args,
        ], {"PATH": _first_on_path(path_dirs(path, manager))}
    # What activation would do, so a program spawning `python` by name gets the
    # venv's rather than the launcher toolset's, which the dispatcher put first.
    return [str(program(path, cmd) or bin_dir(path) / cmd), *args], {
        "VIRTUAL_ENV": str(path),
        "PATH": _first_on_path(path_dirs(path, manager)),
    }
