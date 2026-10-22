#
# Copyright 2026 Tabsdata Inc.
#

"""Process launching -- the single choke point for shelling out.

Every external binary a tool invokes must be declared in that tool's
bin-reqs.txt. Rather than trusting the file to stay current, this module
enforces it: an undeclared binary raises instead of working on the
author's machine and failing on someone else's.
"""

from __future__ import annotations

import functools
import json
import ntpath
import os
import pathlib
import subprocess
import sysconfig


class UndeclaredRequirement(RuntimeError):
    pass


#: Windows finds a program by its name with or without an executable suffix
#: (PATHEXT: .exe, .cmd, ...) and in any case: `uv`, `uv.exe` and `UV.EXE` are
#: one program there. A flag of its own so the rule can be tested anywhere.
WINDOWS = os.name == "nt"
#: What Windows itself falls back to when PATHEXT is not set.
DEFAULT_PATHEXT = ".COM;.EXE;.BAT;.CMD"


def _pathext() -> tuple[str, ...]:
    # PATHEXT is always `;`-separated -- it is Windows' own variable.
    text = os.environ.get("PATHEXT", DEFAULT_PATHEXT)
    return tuple(ext.lower() for ext in text.split(";") if ext)


def _program(name: str) -> str:
    """`name` as the OS compares program names: on Windows without an
    executable suffix and in lower case; elsewhere exactly as written."""
    if not WINDOWS:
        return name
    stem, suffix = os.path.splitext(name)
    return (stem if suffix.lower() in _pathext() else name).lower()


def _pinned(bin_dir: pathlib.Path, binary: str) -> bool:
    """Whether the toolset's own bin/ holds `binary` -- on Windows under any
    of its executable suffixes, as `uv` is `uv.exe` there."""
    if not WINDOWS:
        return (bin_dir / binary).exists()
    stem = _program(binary)
    return any((bin_dir / (stem + ext)).exists() for ext in ("", *_pathext()))


def venv_scripts(venv: pathlib.Path) -> pathlib.Path:
    """A venv's executables dir -- bin/ on Unix, Scripts\\ on Windows -- as the
    running interpreter lays venvs out. The twin of `tabsdata_dev.tdd.paths`'s,
    which common-core cannot import."""
    paths = sysconfig.get_paths(
        scheme="venv", vars={"base": str(venv), "platbase": str(venv)}
    )
    return pathlib.Path(paths["scripts"])


def venv_exe(venv: pathlib.Path, name: str) -> pathlib.Path:
    """A program in a venv, with the platform's executable suffix (.exe on
    Windows)."""
    return venv_scripts(venv) / (name + (sysconfig.get_config_var("EXE") or ""))


@functools.lru_cache(maxsize=1)
def _declared() -> frozenset[str]:
    """Binaries declared by the tool we are running inside.

    Enforcement is skipped when TDD_DIR/_TDD_TOOL are absent, so tools
    stay importable under a bare pytest run.
    """
    dir_ = os.environ.get("TDD_DIR")
    tool = os.environ.get("_TDD_TOOL")
    if not dir_ or not tool:
        return frozenset()
    catalog = pathlib.Path(dir_) / "catalog.json"
    if not catalog.is_file():
        return frozenset()
    entry = json.loads(catalog.read_text(encoding="utf-8"))["tools"].get(tool, {})
    # Required and optional alike: an optional binary is declared, so allowed;
    # whether it is installed is the caller's to check where it uses it.
    family = shell_family()
    return frozenset(
        binary
        for key in ("required", "optional")
        for binary in _for_family(entry.get(key, []), family)
    )


def shell_family() -> str:
    """The twin of `tabsdata_dev.tdd.reqs.shell_family`, which common-core
    cannot import: the family the loader exported, else the platform's own."""
    return os.environ.get("_TDD_SHELL_FAMILY", "").strip() or _default_family()


def _default_family() -> str:
    return "powershell" if WINDOWS else "unix"


def _for_family(value: list | dict, family: str) -> list[str]:
    if isinstance(value, dict):
        return value.get(family, value.get(_default_family(), []))
    return value


@functools.lru_cache(maxsize=1)
def _toolset_bin() -> pathlib.Path | None:
    """This tool's own toolset bin/ (Scripts\\ on Windows), which tdd puts first
    on PATH."""
    dir_ = os.environ.get("TDD_DIR")
    tool = os.environ.get("_TDD_TOOL")
    if not dir_ or not tool:
        return None
    catalog = pathlib.Path(dir_) / "catalog.json"
    if not catalog.is_file():
        return None
    toolset = json.loads(catalog.read_text())["tools"].get(tool, {}).get("toolset")
    return venv_scripts(pathlib.Path(dir_) / "tdd-venvs" / toolset) if toolset else None


def run(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
    """Run a binary, refusing anything neither pinned nor declared.

    A binary is legitimate one of two ways: this toolset provides it
    (a deps-* pin, so it sits in the toolset's bin/), or it is external
    and named in bin-reqs.txt. Anything else is an undeclared
    dependency on whatever happens to be installed.
    """
    _check(argv)
    return subprocess.run(argv, check=kwargs.pop("check", False), **kwargs)


def popen(argv: list[str], **kwargs) -> subprocess.Popen:
    """`run`'s check, for a child the caller streams rather than waits for."""
    _check(argv)
    return subprocess.Popen(argv, **kwargs)


def _check(argv: list[str]) -> None:
    # ntpath splits on both separators, as Windows does: `C:\Git\git.exe`.
    binary = ntpath.basename(argv[0]) if WINDOWS else pathlib.Path(argv[0]).name
    if os.environ.get("_TDD_TOOL"):
        bin_dir = _toolset_bin()
        pinned = bool(bin_dir and _pinned(bin_dir, binary))
        declared = {_program(name) for name in _declared()}
        if not pinned and _program(binary) not in declared:
            tool = os.environ["_TDD_TOOL"]
            dir_ = os.environ.get("TDD_DIR", "")
            # The catalog is what is read, and it is written at install: a
            # requirement added to bin-reqs.txt since then is not in it, and
            # "not declared" would send the reader to a file that declares it.
            raise UndeclaredRequirement(
                f"{binary!r} is neither pinned by this toolset nor declared for "
                f"{tool} in {pathlib.Path(dir_) / 'catalog.json'} -- declare it in "
                f"tabsdata-dev-tool-{tool}/bin-reqs.txt, or if it is there already, "
                f"the install predates it: run `tdd-install --dir {dir_}`"
            )


def tool_argv(name: str, *args: str) -> list[str]:
    """The argv that invokes sibling tool `name` through the dispatcher.

    `tdd` itself is a shell function and cannot be exec'd, so this goes to the
    `tdd-exe` inside the tdd dir the dispatcher exported as TDD_DIR -- which
    also routes the sibling into *its* toolset, whatever this one is. Outside a
    dispatch (a direct development run) it falls back to a `tdd-exe` on PATH.
    Exposed on its own for callers that stream the child (Popen) rather than
    wait for it.
    """
    import shutil

    dir_ = os.environ.get("TDD_DIR")
    if dir_:
        exe = str(venv_exe(pathlib.Path(dir_) / "tdd-venvs" / "tdd", "tdd-exe"))
        return [exe, "--dir", dir_, name, *args]
    exe = shutil.which("tdd-exe")
    if exe is None:
        raise RuntimeError("no tdd dir (TDD_DIR unset) and no tdd-exe on PATH")
    return [exe, name, *args]


def run_tool(name: str, *args: str, **kwargs) -> subprocess.CompletedProcess:
    """Invoke a sibling tool in its own environment, through the dispatcher
    (see `tool_argv`)."""
    return subprocess.run(
        tool_argv(name, *args), check=kwargs.pop("check", False), **kwargs
    )


# ------------------------------------------------------------ process trees
class Job:
    """Windows: a job object holding a child and every process it starts, so
    the tree is terminated whole -- `kill()` there stops one process, and a
    tool behind `tdd-exe` (which waits for it there: Windows has no exec) or a
    shell's pipeline would live on. A process the child starts in the instant
    before it joins the job escapes it; nothing short of creating it suspended
    closes that window, and Popen cannot.

    Elsewhere it holds nothing and `terminate` answers False: a process group
    does this job there."""

    def __init__(self, pid: int) -> None:
        self._handle = _windows_job(pid) if os.name == "nt" else None

    def terminate(self) -> bool:
        """End the whole tree; False when there is no job to do it with."""
        if self._handle is None:
            return False
        _windows_terminate(self._handle)
        return True

    def close(self) -> None:
        if self._handle is not None:
            _windows_close(self._handle)
            self._handle = None


def _windows_job(pid: int):
    """A job object holding `pid`, or None when one cannot be made (the tree
    then falls back to killing the child alone)."""
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CreateJobObjectW.restype = wintypes.HANDLE
    k32.CreateJobObjectW.argtypes = [wintypes.LPVOID, wintypes.LPCWSTR]
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    process_terminate, process_set_quota = 0x0001, 0x0100
    job = k32.CreateJobObjectW(None, None)
    if not job:
        return None
    handle = k32.OpenProcess(process_terminate | process_set_quota, False, pid)
    assigned = bool(handle) and bool(k32.AssignProcessToJobObject(job, handle))
    if handle:
        k32.CloseHandle(handle)
    if not assigned:
        k32.CloseHandle(job)
        return None
    return job


def _windows_terminate(job) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.TerminateJobObject.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateJobObject(job, 1)


def _windows_close(job) -> None:
    import ctypes
    from ctypes import wintypes

    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle(job)
