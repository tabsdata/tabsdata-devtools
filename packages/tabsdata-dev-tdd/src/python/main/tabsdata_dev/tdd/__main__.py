#
# Copyright 2026 Tabsdata Inc.
#

"""tdd-exe -- one entry point for every tabsdata dev tool.

    tdd [--dir TDD_PATH] <word> [args...]
    tdd [--dir TDD_PATH] --reqs [TOOL]

`<word>` is a builtin or a tool name; everything after it is passed to the
tool untouched. Standard library only.

Two things that look like they belong here do not. Setting a tdd dir up is
`tdd-install`, a separate executable, because the `tdd` shell function cannot
exist before it has run. Regenerating the catalog is `cargo make gen`, a build
step that has to run before wheels are built, never from a finished install.
"""

from __future__ import annotations

import pathlib
import sys

from . import catalog as catalog_mod, dispatch as dispatch_mod
from . import initialize as initialize_mod, paths, reqs as reqs_mod
from . import version as version_mod

BUILTIN_SUMMARIES = {
    "list": "list available tools; --demo includes the demo tools",
    "doctor": "validate TDD_PATH against the installed catalog",
    "info": "describe TDD_PATH: install kind, checkout, version, envs",
}

USAGE = """\
usage: tdd-exe [--dir TDD_PATH] <word> [args...]

Prefer the `tdd` shell function, which also reaches the sourced shell
commands: source $TDD_DIR/tdd-source.sh (written by tdd-install).

builtins:
  list [--porcelain] [--demo]
                    list available tools; demo tools only with --demo
  doctor            validate TDD_PATH against the installed catalog
  info              describe TDD_PATH: install kind, checkout, version, envs

options:
  --dir TDD_PATH    default: $TDD_DIR, else ~/.tdd
  --reqs [TOOL]     report external binaries; non-zero exit if any missing
  --version         the VERSION stamped into TDD_PATH, else the shipped one
  --help

Setting a tdd dir up is `tdd-install [--dir TDD_PATH] [--relock] [--from-wheels]`.
"""


def _split(argv: list[str]) -> tuple[dict, list[str]]:
    """Parse only what precedes <word>. Everything after belongs to the tool."""
    opts: dict = {"dir": None, "reqs": False}
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dir":
            if i + 1 >= len(argv):
                raise SystemExit("tdd: --dir needs a path")
            opts["dir"] = argv[i + 1]
            i += 2
        elif arg.startswith("--dir="):
            opts["dir"] = arg.split("=", 1)[1]
            i += 1
        elif arg == "--reqs":
            opts["reqs"] = True
            i += 1
        elif arg in ("-h", "--help"):
            opts["help"] = True
            i += 1
        elif arg == "--version":
            opts["version"] = True
            i += 1
        else:
            break
    return opts, argv[i:]


def _listed(catalog: dict, demo: bool) -> list[tuple[str, dict]]:
    """Tools worth showing: the demo ones only when asked for.

    Hiding is a listing concern only -- a demo tool still dispatches, tests
    and reports reqs like any other, so nothing else consults the flag.
    """
    return sorted(
        (name, entry)
        for name, entry in catalog["tools"].items()
        if demo or not entry.get("demo", False)
    )


def _porcelain(demo: bool) -> int:
    """Machine-readable `name|kind|summary`, one per line.

    This is what the `tdd` shell function reads to merge its own sourced
    commands into one alphabetical help listing.
    """
    for name in sorted(paths.BUILTINS):
        print(f"{name}|builtin|{BUILTIN_SUMMARIES[name]}")
    try:
        catalog = catalog_mod.installed(paths.tdd_dir(None))
    except catalog_mod.NotInitialized:
        catalog = catalog_mod.shipped()
    for name, entry in _listed(catalog, demo):
        print(f"{name}|{entry['toolset']}|{entry['summary']}")
    return 0


def _list(dir_: pathlib.Path, demo: bool) -> int:
    try:
        catalog = catalog_mod.installed(dir_)
        where = str(dir_)
    except catalog_mod.NotInitialized:
        catalog = catalog_mod.shipped()
        where = "not initialized -- showing the installed catalog"
    print(f"tools ({where}):")
    listed = _listed(catalog, demo)
    for name, entry in listed:
        print(f"  {name:<12} {entry['toolset']:<10} {entry['summary']}")
    if not listed:
        hidden = len(catalog["tools"])
        print(
            f"  (none; {hidden} demo tools hidden -- add --demo)"
            if hidden
            else "  (none)"
        )
    return 0


def _info(dir_: pathlib.Path) -> int:
    try:
        catalog = catalog_mod.installed(dir_)
    except catalog_mod.NotInitialized as exc:
        print(f"tdd: {exc}", file=sys.stderr)
        return 2
    # tdd-exe lives inside the tdd dir, so how *it* was installed is how the
    # dir was built: editable from a checkout, or from wheels staged in it.
    root = paths.repo_root()
    print(f"tdd dir    {dir_}")
    if root is not None:
        print(f"install    source (editable), checkout at {root}")
    else:
        staged = dir_ / "wheels"
        print(
            "install    wheels" + (f", staged in {staged}" if staged.is_dir() else "")
        )
    print(f"version    {version_mod.current(dir_)}")
    print(f"catalog    {dir_ / catalog_mod.CATALOG_NAME}")
    print(f"source     {dir_ / initialize_mod.SOURCE_NAME}")
    print(f"venvs      {paths.venvs_dir(dir_)}")
    print(f"toolsets   {' '.join(catalog['toolsets'])}")
    for label, entries in (
        ("tools", catalog["tools"]),
        ("shell", catalog.get("shell", {})),
    ):
        demo = sum(1 for entry in entries.values() if entry.get("demo"))
        print(f"{label:<10} {len(entries)}" + (f" ({demo} demo)" if demo else ""))
    return 0


def _doctor(dir_: pathlib.Path) -> int:
    problems = 0
    try:
        catalog = catalog_mod.installed(dir_)
    except catalog_mod.NotInitialized as exc:
        print(f"  [fail] {exc}")
        return 1
    print(f"tdd dir: {dir_}")
    # Informational: an editable dir legitimately lags the checkout until the
    # next tdd-install, and a wheels dir is whatever was staged into it.
    stamped, shipped = version_mod.installed(dir_), version_mod.shipped()
    if stamped == shipped:
        print(f"  [ok]   version {stamped}")
    else:
        print(
            f"  [note] version {stamped or '<unstamped>'} (this tdd-exe ships {shipped})"
        )
    if catalog_mod.is_stale(dir_):
        problems += 1
        print("  [fail] catalog is stale; run `tdd-install`")
    else:
        print("  [ok]   catalog matches the installed tool set")
    # The envs are relocatable, but their interpreter is not inside the tree:
    # bin/python symlinks to the uv-managed Python by absolute path. A tdd dir
    # moved to another machine, or one whose uv Python was removed, fails here
    # rather than anywhere obvious -- so check it explicitly.
    for env in sorted(paths.venvs_dir(dir_).glob("*")):
        if not env.is_dir():
            continue
        python = env / "bin" / "python"
        if python.exists():
            print(f"  [ok]   env {env.name}: interpreter present")
        else:
            problems += 1
            target = python.readlink() if python.is_symlink() else "<missing>"
            print(f"  [fail] env {env.name}: interpreter unreachable -> {target}")
            print("         reinstall on this machine, or `uv python install`")

    for name, entry in sorted(catalog["tools"].items()):
        exe = paths.venvs_dir(dir_) / entry["toolset"] / "bin" / name
        if exe.is_file():
            print(f"  [ok]   {name}")
        else:
            problems += 1
            print(f"  [fail] {name}: missing {exe}")
    return 1 if problems else 0


def main(argv: list[str] | None = None) -> int:
    try:
        return _run(argv)
    except paths.UvMissing as exc:
        # uv is not optional anywhere in tdd; say so plainly rather than
        # letting a traceback carry the message.
        print(f"tdd: {exc}", file=sys.stderr)
        return 2


def _run(argv: list[str] | None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    opts, rest = _split(argv)

    if opts.get("help") or (not rest and not opts["reqs"] and not opts.get("version")):
        print(USAGE, end="")
        return 0

    dir_ = paths.tdd_dir(opts["dir"])

    if opts.get("version"):
        print(f"tdd {version_mod.current(dir_)}")
        return 0
    if opts["reqs"]:
        return reqs_mod.check(rest[0] if rest else None)

    word, tool_argv = rest[0], rest[1:]

    if word == "list":
        demo = "--demo" in tool_argv
        if "--porcelain" in tool_argv:
            return _porcelain(demo)
        return _list(dir_, demo)
    if word == "doctor":
        return _doctor(dir_)
    if word == "info":
        return _info(dir_)

    try:
        return dispatch_mod.dispatch(dir_, word, tool_argv)
    except catalog_mod.NotInitialized as exc:
        print(f"tdd: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
