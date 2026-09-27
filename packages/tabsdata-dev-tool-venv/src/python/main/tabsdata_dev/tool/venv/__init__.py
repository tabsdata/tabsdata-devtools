#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd _venv`` -- the managed venvs of `tdd venv`, everything but entering one.

    tdd _venv create --name NAME [--type pyenv|uv|conda] [--python VERSION] [--relocatable] [--force]
    tdd _venv delete (--name NAME | --all) [--active NAME]
    tdd _venv list [--active NAME]
    tdd _venv info --name NAME
    tdd _venv migrate

A managed venv lives at ``<tdd_dir>/managed-venvs/<type>/<name>`` with a
``<name>.json`` marker beside the type directories (see
``common.core.managedvenv``, which reads it for the launchers). This tool builds
a venv and writes its marker, removes one, lists them, describes one, and
migrates the pre-JSON ``<name>.env`` markers -- what the shell half of `tdd
venv` used to do itself, in sh and again in PowerShell. What is left there is
what only a shell can do: activate, deactivate, adopt a venv entered by hand,
refuse a foreign one, paint the prompt.

It knows nothing of the calling shell, so where the answer depends on which
venv is active the shell says (``--active NAME``): delete refuses the active
one, list marks it. A venv is described from its own python -- asked, never
assumed -- found in ``bin/`` or, built on Windows, ``Scripts\\``.

The leading underscore makes it plumbing (`tdd -x` lists it); xp also drives it,
for the one-off venvs of an execute stage.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import re
import shutil
import subprocess

from tabsdata_dev.common.core import cli, datadir, managedvenv, render
from tabsdata_dev.common.core.errors import ToolError

NAME = "_venv"
DESCRIPTION = (
    "plumbing of tdd venv: create, delete, list and describe managed venvs (no activation)"
)

#: One interpreter across every venv tdd makes, whichever tool makes it: what a
#: tdkserver instance builds its own environments with.
DEFAULT_PYTHON = "3.12.13"
DEFAULT_TYPE = "pyenv"
SCHEMA = 1
_NAME_OK = re.compile(r"^[A-Za-z0-9._-]+$")


# ------------------------------------------------------------------ layout ---


def venv_dir(name: str, manager: str) -> pathlib.Path:
    return managedvenv.root() / manager / name


def python_of(prefix: pathlib.Path) -> pathlib.Path | None:
    """The venv's own interpreter: ``bin/python`` on Unix, ``Scripts\\python.exe``
    (or ``python.exe`` at the root of a Windows conda env) otherwise."""
    for leaf in ("python", "python3", "python.exe"):
        candidate = managedvenv.bin_dir(prefix) / leaf
        if candidate.is_file():
            return candidate
    root_exe = prefix / "python.exe"
    return root_exe if root_exe.is_file() else None


def probe(prefix: pathlib.Path) -> tuple[str, str]:
    """What the venv says about itself: its python's version and the base
    interpreter it was built from (``sys._base_executable``, which pyvenv.cfg's
    ``home`` points at; a conda env carries its own). Empty when it does not run."""
    py = python_of(prefix)
    if py is None:
        return "", ""
    done = subprocess.run(
        [
            str(py),
            "-c",
            "import sys; print(sys.version.split()[0]); "
            "print(sys._base_executable or sys.executable)",
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        return "", ""
    lines = done.stdout.splitlines()
    return (lines[0] if lines else ""), (lines[1] if len(lines) > 1 else "")


def now() -> str:
    """As the markers stamp it: UTC, to the second."""
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def manager_version(manager: str) -> str:
    """The second word of `<manager> --version`: `uv 0.12.3 (...)`, `pyenv 2.8.4`."""
    try:
        done = subprocess.run([manager, "--version"], capture_output=True, text=True)
    except OSError:
        return ""
    words = (done.stdout.splitlines() or [""])[0].split()
    return words[1] if len(words) > 1 else ""


def tdd_version() -> str:
    try:
        return (datadir.tdd_dir() / "VERSION").read_text().strip()
    except OSError:
        return ""


def write_marker(
    name: str,
    manager: str,
    python: str,
    python_path: str,
    relocatable: bool,
    created: str,
    requested: str,
    mver: str,
    migrated: bool = False,
) -> None:
    """The marker, through a temporary file and one rename, so an interrupted
    write never leaves half a marker. An empty fact is null."""

    def opt(value: str) -> str | None:
        return value or None

    doc = {
        "schema": SCHEMA,
        "name": name,
        "manager": manager,
        "manager_version": opt(mver),
        "python": opt(python),
        "python_requested": opt(requested),
        "python_path": opt(python_path),
        "relocatable": relocatable,
        "created": opt(created),
        "tdd_version": opt(tdd_version()),
    }
    if migrated:
        doc["migrated"] = now()
    path = managedvenv.marker_path(name)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        tmp.write_text(json.dumps(doc) + "\n", encoding="utf-8")
        tmp.replace(path)
    except OSError as exc:
        tmp.unlink(missing_ok=True)
        raise ToolError(f"cannot write {path}", str(exc)) from exc


def markers() -> list[str]:
    """Every managed venv's name, from its marker, sorted."""
    try:
        return sorted(p.name[: -len(managedvenv.MARKER_SUFFIX)] for p in managedvenv.root().glob("*.json"))
    except OSError:
        return []


def remove(name: str, manager: str, out: render.Renderer) -> None:
    """The venv and its marker. A conda env is forgotten by conda first (the
    rmtree covers a partial one)."""
    prefix = venv_dir(name, manager)
    if manager == "conda" and prefix.is_dir():
        subprocess.run(
            ["conda", "env", "remove", "-y", "-q", "--prefix", str(prefix)],
            capture_output=True,
        )
    try:
        if prefix.exists():
            shutil.rmtree(prefix)
    except OSError as exc:
        raise ToolError(f"could not remove {prefix}", str(exc)) from exc
    managedvenv.marker_path(name).unlink(missing_ok=True)
    out.debug(f"removed {name} ({manager})")


def described(name: str, active: str = "") -> dict:
    """What `list` and `info` say of one venv, from its marker."""
    m = managedvenv.marker(name) or {}
    manager = m.get("manager", "")
    prefix = venv_dir(name, manager)
    return {
        "name": name,
        "type": manager,
        "python": m.get("python") or "",
        "python_path": m.get("python_path") or "",
        "relocatable": m.get("relocatable") is True,
        "created": m.get("created") or "",
        "path": str(prefix),
        "active": bool(active) and active == name,
        "exists": prefix.is_dir(),
    }


# ------------------------------------------------------------------ migrate ---


def migrate(out: render.Renderer) -> int:
    """Replace every pre-JSON ``<name>.env`` (the type alone) by a ``<name>.json``:
    the type from the file, the interpreter probed from the venv, relocatable
    from what uv writes in pyvenv.cfg, created from the old marker's mtime. So
    the two formats never coexist and no reader has to know the old one."""
    done = 0
    for old in sorted(managedvenv.root().glob(f"*{managedvenv.LEGACY_MARKER_SUFFIX}")):
        name = old.name[: -len(managedvenv.LEGACY_MARKER_SUFFIX)]
        manager = old.read_text(encoding="utf-8", errors="replace").strip()
        if manager not in managedvenv.MANAGERS:
            out.warn(f"{old} names an unknown venv manager '{manager}'; left as it is")
            continue
        prefix = venv_dir(name, manager)
        python, python_path = probe(prefix)
        try:
            cfg = (prefix / "pyvenv.cfg").read_text(encoding="utf-8", errors="replace")
        except OSError:
            cfg = ""
        relocatable = any(line.strip() == "relocatable = true" for line in cfg.splitlines())
        created = datetime.datetime.fromtimestamp(old.stat().st_mtime, datetime.timezone.utc).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
        write_marker(name, manager, python, python_path, relocatable, created, "", "", migrated=True)
        old.unlink()
        out.debug(f"migrated the marker of {name} ({manager}) to {managedvenv.marker_path(name)}")
        done += 1
    return done


# ------------------------------------------------------------------- create ---


def _build(manager: str, prefix: pathlib.Path, python: str, relocatable: bool) -> None:
    """Make the venv at `prefix` with `manager`; raise with what it said."""
    if manager == "uv":
        # --managed-python: uv's own interpreters only, never the homebrew,
        # pyenv or system python on PATH under the same version. Relocatable
        # only when asked, and UV_VENV_RELOCATABLE kept out: the marker records
        # what the venv is, so the environment must not decide it.
        argv = ["uv", "venv", "--managed-python"]
        if relocatable:
            argv.append("--relocatable")
        if python:
            argv += ["--python", python]
        env = {k: v for k, v in os.environ.items() if k != "UV_VENV_RELOCATABLE"}
        done = subprocess.run([*argv, str(prefix)], capture_output=True, text=True, env=env)
    elif manager == "pyenv":
        # A plain venv on a pyenv interpreter: pyenv's virtualenv plugin cannot
        # place an env outside its versions dir.
        found = subprocess.run(
            ["pyenv", "prefix", *([python] if python else [])], capture_output=True, text=True
        )
        if found.returncode != 0:
            raise ToolError(
                f"pyenv has no {python or 'current'} version; run: pyenv install {python or 'VERSION'}",
                found.stderr or found.stdout,
            )
        base = pathlib.Path(found.stdout.strip())
        interp = next(
            (base / rel for rel in ("bin/python3", "bin/python", "python.exe") if (base / rel).is_file()),
            None,
        )
        if interp is None:
            raise ToolError(f"no python under pyenv prefix {base}")
        done = subprocess.run([str(interp), "-m", "venv", str(prefix)], capture_output=True, text=True)
    else:
        spec = f"python={python}" if python else "python"
        done = subprocess.run(
            ["conda", "create", "-y", "-q", "--prefix", str(prefix), spec], capture_output=True, text=True
        )
    if done.returncode != 0:
        raise ToolError(f"{manager} failed to create {prefix.name}", (done.stdout or "") + (done.stderr or ""))


def create(args: argparse.Namespace, out: render.Renderer) -> int:
    name, manager, python = args.name, args.type, args.python
    if not _NAME_OK.match(name) or name.startswith("."):
        raise ToolError(f"invalid name: {name} (letters, digits, . _ - only; no leading dot)")
    if manager not in managedvenv.MANAGERS:
        raise ToolError(f"unknown --type: {manager} (pyenv, uv or conda)")
    # Only uv builds a venv that survives a move; `python -m venv` and conda
    # bake the path in, so asking is a mistake worth stopping on.
    if args.relocatable and manager != "uv":
        raise ToolError(f"--relocatable needs --type uv: a {manager} venv is bound to its path")
    recreated = False
    previous = managedvenv.marker(name)
    if managedvenv.marker_path(name).exists():
        was = (previous or {}).get("manager", "?")
        if not args.force:
            raise ToolError(f"a managed venv named {name} already exists (type {was}); --force recreates it")
        # Removed under its OLD type -- the new one may differ -- so nothing
        # stale survives. The shell has left it first if it was the active one.
        out.info(f"recreate {name} (was {was})")
        remove(name, was, out)
        recreated = True
    if shutil.which(manager) is None:
        raise ToolError(f"{manager} is not on PATH")
    prefix = venv_dir(name, manager)
    try:
        prefix.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        raise ToolError(f"cannot create {prefix.parent}", str(exc)) from exc
    out.info(f"create {name} ({manager}{', relocatable' if args.relocatable else ''})")
    out.debug(f"python: {python or 'default'}")
    try:
        _build(manager, prefix, python, args.relocatable)
        # What the venv turned out to be, asked of its own python, beside what
        # was asked for and who made it.
        py, py_path = probe(prefix)
        created = now()
        write_marker(name, manager, py, py_path, args.relocatable, created, python, manager_version(manager))
    except BaseException:
        shutil.rmtree(prefix, ignore_errors=True)
        raise
    return out.ok(
        f"{'re' if recreated else ''}created {name} ({manager}, python {py or '?'}"
        f"{', relocatable' if args.relocatable else ''}) at {prefix}",
        name=name,
        type=manager,
        path=str(prefix),
        python=py,
        python_requested=python,
        python_path=py_path,
        relocatable=args.relocatable,
        created=created,
        recreated=recreated,
    )


# --------------------------------------------------------- delete, list, info ---


def delete(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.all:
        if args.name:
            raise ToolError("--all and --name are exclusive")
        # None may be active: the same rule as for one, and it keeps this from
        # pulling the venv the shell stands in out from under it.
        if args.active:
            raise ToolError(f"{args.active} is active; run tdd venv deactivate first")
        gone = []
        for name in markers():
            manager = (managedvenv.marker(name) or {}).get("manager", "")
            out.info(f"delete {name} ({manager})")
            remove(name, manager, out)
            gone.append({"name": name, "type": manager})
        if not gone:
            return out.ok("no managed venvs to delete", deleted=[])
        return out.ok("deleted " + ", ".join(f"{g['name']} ({g['type']})" for g in gone), deleted=gone)
    if not args.name:
        raise ToolError("--name NAME or --all is required")
    m = managedvenv.marker(args.name)
    if m is None:
        raise ToolError(f"no managed venv named {args.name} (see tdd venv list)")
    if args.active == args.name:
        raise ToolError(f"{args.name} is active; run tdd venv deactivate first")
    out.info(f"delete {args.name} ({m['manager']})")
    remove(args.name, m["manager"], out)
    return out.ok(f"deleted {args.name} ({m['manager']})", name=args.name, type=m["manager"])


def listing(args: argparse.Namespace, out: render.Renderer) -> int:
    rows, venvs = [], []
    for name in markers():
        if managedvenv.marker(name) is None:
            continue
        d = described(name, args.active)
        mark = ("  (active)" if d["active"] else "") + ("" if d["exists"] else "  (missing directory)")
        # name, type, the python it runs, reloc or -, its path, the base python
        # it was built from: everything the marker knows, one line.
        rows.append(
            f"{name:<24} {d['type']:<6} {d['python'] or '?':<9} {'reloc' if d['relocatable'] else '-':<6} "
            f"{d['path']}  {d['python_path'] or '?'}{mark}"
        )
        venvs.append(d)
    if not rows:
        return out.ok("no managed venvs (create one: tdd venv create --name NAME)", venvs=[])
    return out.ok("\n".join(rows), venvs=venvs)


def info(args: argparse.Namespace, out: render.Renderer) -> int:
    if managedvenv.marker(args.name) is None:
        raise ToolError(f"no managed venv named {args.name} (see tdd venv list)")
    d = described(args.name)
    return out.ok(f"{args.name} ({d['type']}, python {d['python'] or '?'}) at {d['path']}", **d)


# -------------------------------------------------------------------- wiring ---


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action is None:
        raise ToolError("a subcommand is required: create, delete, list, info or migrate (see --help)")
    # Every subcommand but migrate itself migrates first, so nothing after
    # ever meets a pre-JSON marker.
    migrated = migrate(out)
    if args.action == "migrate":
        return out.ok(f"migrated {migrated} marker(s)", migrated=migrated)
    return {"create": create, "delete": delete, "list": listing, "info": info}[args.action](args, out)


def _common(sub: argparse.ArgumentParser) -> None:
    """The options every command has, repeated on the subcommand, so they may
    follow its word (SUPPRESS: an unused copy must not overwrite one before it)."""
    sub.add_argument(
        "--format", choices=("json", "view"), default=argparse.SUPPRESS, help="json is JSON Lines (default: view)"
    )
    sub.add_argument("--verbose", "-v", action="store_true", default=argparse.SUPPRESS, help="show debug events too")


def configure(p: argparse.ArgumentParser) -> None:
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    c = sub.add_parser("create", help="build a managed venv and write its marker (no activation)")
    c.add_argument("--name", required=True, help="the venv's name (letters, digits, . _ -)")
    c.add_argument("--type", default=DEFAULT_TYPE, choices=managedvenv.MANAGERS, help=f"(default: {DEFAULT_TYPE})")
    c.add_argument("--python", default=DEFAULT_PYTHON, help=f"the interpreter version (default: {DEFAULT_PYTHON})")
    c.add_argument("--relocatable", action="store_true", help="a venv that survives a move (uv only)")
    c.add_argument("--force", "-f", action="store_true", help="recreate a venv of that name")
    _common(c)
    d = sub.add_parser("delete", help="remove a managed venv and its marker, or all of them")
    d.add_argument("--name", default="", help="the venv to delete")
    d.add_argument("--all", action="store_true", help="every managed venv")
    d.add_argument("--active", default="", metavar="NAME", help="the venv the calling shell has active")
    _common(d)
    ls = sub.add_parser("list", help="every managed venv, from its marker")
    ls.add_argument("--active", default="", metavar="NAME", help="the venv the calling shell has active")
    _common(ls)
    i = sub.add_parser("info", help="what the marker of one venv records, and where it is")
    i.add_argument("--name", required=True, help="the venv to describe")
    _common(i)
    m = sub.add_parser("migrate", help="replace pre-JSON <name>.env markers by <name>.json")
    _common(m)


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)
