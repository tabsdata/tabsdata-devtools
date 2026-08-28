#
# Copyright 2026 Tabsdata Inc.
#

"""tdd-exe -- one entry point for every tabsdata dev tool.

    tdd [--dir TDD_PATH] <word> [args...]
    tdd [--dir TDD_PATH] --reqs [TOOL]
    tdd-exe [--dir TDD_PATH] --porcelain [--demo]
    tdd-exe [--dir TDD_PATH] --defaults <command> [args...]

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

from . import catalog as catalog_mod, defaults as defaults_mod, dispatch as dispatch_mod
from . import initialize as initialize_mod, paths, render, reqs as reqs_mod
from . import version as version_mod

BUILTIN_SUMMARIES = {
    "doctor": "validate TDD_PATH against the installed catalog",
    "info": "describe TDD_PATH: install kind, checkout, version, envs",
}

USAGE = """\
usage: tdd-exe [--dir TDD_PATH] <word> [args...]

Prefer the `tdd` shell function, which also reaches the sourced shell
commands: source $TDD_DIR/tdd-source.sh (written by tdd-install).

builtins:
  doctor            validate TDD_PATH against the installed catalog
  info              describe TDD_PATH: install kind, checkout, version, envs

options:
  --dir TDD_PATH    default: $TDD_DIR, else ~/.tdd
  --format json|view
                    how tdd-exe itself reports (default view); builtins also
                    accept it after the word
  --verbose, -v     show debug events too
  --reqs [TOOL]     report external binaries; exit 1 if any missing
  --version         the VERSION stamped into TDD_PATH, else the shipped one
  --porcelain [--demo]
                    machine-readable `name|kind|summary` lines: what the `tdd`
                    shell function merges into `tdd help`
  --defaults <command> [args...]
                    merge TDD_PATH/default-opts/<command>.txt into the args and
                    print the result one per line (first line: the files used);
                    what the `tdd` shell function calls before dispatching
  --help

Default options: put `--name value` lines in TDD_PATH/default-opts/<command>.txt
(or <command>_<action>.txt, e.g. venv_create.txt); typed options win over them.

Setting a tdd dir up is `tdd-install [--dir TDD_PATH] [--relock] [--from-wheels]`.
"""


def _split(argv: list[str]) -> tuple[dict, list[str]]:
    """Parse only what precedes <word>. Everything after belongs to the tool."""
    opts: dict = {
        "dir": None,
        "reqs": False,
        "porcelain": False,
        "defaults": False,
        "format": "view",
        "verbose": False,
    }
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--dir":
            if i + 1 >= len(argv):
                raise UsageError("--dir needs a path")
            opts["dir"] = argv[i + 1]
            i += 2
        elif arg.startswith("--dir="):
            opts["dir"] = arg.split("=", 1)[1]
            i += 1
        elif arg == "--format":
            if i + 1 >= len(argv):
                raise UsageError("--format needs json or view")
            opts["format"] = argv[i + 1]
            i += 2
        elif arg.startswith("--format="):
            opts["format"] = arg.split("=", 1)[1]
            i += 1
        elif arg in ("-v", "--verbose"):
            opts["verbose"] = True
            i += 1
        elif arg == "--reqs":
            opts["reqs"] = True
            i += 1
        elif arg == "--porcelain":
            opts["porcelain"] = True
            i += 1
        elif arg == "--defaults":
            opts["defaults"] = True
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


class UsageError(Exception):
    pass


def _builtin_opts(word: str, argv: list[str], opts: dict) -> render.Renderer:
    """A builtin takes --format/--verbose after the word too, and nothing else."""
    fmt, verbose = opts["format"], opts["verbose"]
    i = 0
    while i < len(argv):
        arg = argv[i]
        if arg == "--format" and i + 1 < len(argv):
            fmt = argv[i + 1]
            i += 2
        elif arg.startswith("--format="):
            fmt = arg.split("=", 1)[1]
            i += 1
        elif arg in ("-v", "--verbose"):
            verbose = True
            i += 1
        else:
            raise UsageError(f"{word} takes no argument {arg!r}")
    return _renderer(word, fmt, verbose)


def _renderer(command: str, fmt: str, verbose: bool) -> render.Renderer:
    if fmt not in ("json", "view"):
        raise UsageError(f"--format must be json or view, got {fmt!r}")
    return render.Renderer(command, fmt=fmt, verbose=verbose)


def _listed(catalog: dict, demo: bool) -> list[tuple[str, dict]]:
    """Tools worth showing in `tdd help`: the demo ones only when asked for.

    Hiding is a listing concern only -- a demo tool still dispatches, tests
    and reports reqs like any other, so nothing else consults the flag.
    """
    return sorted(
        (name, entry)
        for name, entry in catalog["tools"].items()
        if demo or not entry.get("demo", False)
    )


def _porcelain(dir_: pathlib.Path, demo: bool) -> int:
    """Machine-readable `name|kind|summary`, one per line.

    This is what the `tdd` shell function reads to merge its own sourced
    commands into one alphabetical help listing -- the only listing there is.
    A separate `list` word was dropped: `tdd help` already shows every tool,
    and `tdd info` the counts.
    """
    for name in sorted(paths.BUILTINS):
        print(f"{name}|builtin|{BUILTIN_SUMMARIES[name]}")
    try:
        catalog = catalog_mod.installed(dir_)
    except catalog_mod.NotInitialized:
        catalog = catalog_mod.shipped()
    for name, entry in _listed(catalog, demo):
        print(f"{name}|{entry['toolset']}|{entry['summary']}")
    return 0


def _info(dir_: pathlib.Path, out: render.Renderer) -> int:
    try:
        catalog = catalog_mod.installed(dir_)
    except catalog_mod.NotInitialized as exc:
        return out.error(str(exc))
    out.debug(f"catalog: {dir_ / catalog_mod.CATALOG_NAME}")
    # tdd-exe lives inside the tdd dir, so how *it* was installed is how the
    # dir was built: editable from a checkout, or from wheels staged in it.
    root = paths.repo_root()
    staged = dir_ / "wheels"
    shell = catalog.get("shell", {})
    fields = {
        "tdd_dir": str(dir_),
        "install": "source" if root is not None else "wheels",
        "checkout": str(root) if root is not None else None,
        "staged_wheels": str(staged) if root is None and staged.is_dir() else None,
        "version": version_mod.current(dir_),
        "catalog": str(dir_ / catalog_mod.CATALOG_NAME),
        "source": str(dir_ / initialize_mod.SOURCE_NAME),
        "venvs": str(paths.venvs_dir(dir_)),
        "default_opts": str(defaults_mod.defaults_dir(dir_)),
        "toolsets": catalog["toolsets"],
        "tools": len(catalog["tools"]),
        "demo_tools": sum(1 for e in catalog["tools"].values() if e.get("demo")),
        "shell": len(shell),
        "demo_shell": sum(1 for e in shell.values() if e.get("demo")),
    }
    if root is not None:
        install = f"source (editable), checkout at {root}"
    else:
        install = "wheels" + (f", staged in {staged}" if staged.is_dir() else "")

    def count(n: int, demo: int) -> str:
        return f"{n}" + (f" ({demo} demo)" if demo else "")

    lines = [
        f"tdd dir       {dir_}",
        f"install       {install}",
        f"version       {fields['version']}",
        f"catalog       {fields['catalog']}",
        f"source        {fields['source']}",
        f"venvs         {fields['venvs']}",
        f"default-opts  {fields['default_opts']}",
        f"toolsets      {' '.join(catalog['toolsets'])}",
        f"tools         {count(fields['tools'], fields['demo_tools'])}",
        f"shell         {count(fields['shell'], fields['demo_shell'])}",
    ]
    return out.ok("\n".join(lines), **fields)


def _doctor(dir_: pathlib.Path, out: render.Renderer) -> int:
    problems: list[str] = []

    def check(ok: bool, message: str, **fields) -> None:
        if ok:
            out.info(f"[ok]   {message}", ok=True, **fields)
        else:
            problems.append(message)
            out.warn(f"[fail] {message}", ok=False, **fields)

    try:
        catalog = catalog_mod.installed(dir_)
    except catalog_mod.NotInitialized as exc:
        return out.error(str(exc))
    out.debug(
        f"catalog: {dir_ / catalog_mod.CATALOG_NAME} (shipped: {catalog_mod.shipped_path()})"
    )
    out.info(f"tdd dir: {dir_}")
    # Informational: an editable dir legitimately lags the checkout until the
    # next tdd-install, and a wheels dir is whatever was staged into it.
    stamped, shipped = version_mod.installed(dir_), version_mod.shipped()
    if stamped == shipped:
        out.info(f"[ok]   version {stamped}", check="version", ok=True)
    else:
        out.warn(
            f"[note] version {stamped or '<unstamped>'} (this tdd-exe ships {shipped})",
            check="version",
        )
    check(
        not catalog_mod.is_stale(dir_),
        "catalog matches the installed tool set",
        check="catalog",
    )
    # The envs are relocatable, but their interpreter is not inside the tree:
    # bin/python symlinks to the uv-managed Python by absolute path. A tdd dir
    # moved to another machine, or one whose uv Python was removed, fails here
    # rather than anywhere obvious -- so check it explicitly.
    for env in sorted(paths.venvs_dir(dir_).glob("*")):
        if not env.is_dir():
            continue
        python = env / "bin" / "python"
        if python.exists():
            check(
                True,
                f"env {env.name}: interpreter present",
                check="interpreter",
                env=env.name,
            )
        else:
            target = python.readlink() if python.is_symlink() else "<missing>"
            check(
                False,
                f"env {env.name}: interpreter unreachable -> {target}",
                check="interpreter",
                env=env.name,
            )
    for name, entry in sorted(catalog["tools"].items()):
        exe = paths.venvs_dir(dir_) / entry["toolset"] / "bin" / name
        check(
            exe.is_file(),
            name if exe.is_file() else f"{name}: missing {exe}",
            check="tool",
            tool=name,
        )
    if problems:
        return out.error(
            f"{len(problems)} problems in {dir_}; reinstall here (tdd-install) "
            "or `uv python install`",
            problems=problems,
        )
    return out.ok(f"{dir_} is healthy", checks=len(catalog["tools"]) + 2)


def _defaults(dir_: pathlib.Path, rest: list[str]) -> int:
    """Plumbing for the `tdd` shell function: the resolved command line, one
    argument per line, after a first line naming the files used. Nothing at
    all when no defaults file applies, so the caller keeps what was typed.
    Errors go to stderr as plain text: the shell relays them as its own event."""
    if not rest:
        print("tdd: --defaults needs a command word", file=sys.stderr)
        return 1
    try:
        resolved = defaults_mod.resolve(dir_, rest[0], rest[1:])
    except defaults_mod.DefaultsError as exc:
        print(f"tdd: {exc}", file=sys.stderr)
        return 1
    if resolved is None:
        return 0
    merged, sources = resolved
    print("# " + " ".join(sources))
    for arg in merged:
        print(arg)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    try:
        return _run(argv)
    except paths.UvMissing as exc:
        # uv is not optional anywhere in tdd; say so plainly rather than
        # letting a traceback carry the message.
        return _fallback(argv).error(str(exc))
    except UsageError as exc:
        return _fallback(argv).error(f"{exc} (see --help)")


def _fallback(argv: list[str]) -> render.Renderer:
    """A renderer for errors raised before or while parsing: honour a
    --format the user managed to type, wherever it sits, else view."""
    fmt = "view"
    for i, arg in enumerate(argv):
        if arg == "--format" and i + 1 < len(argv) and argv[i + 1] in ("json", "view"):
            fmt = argv[i + 1]
        elif arg.startswith("--format=") and arg[9:] in ("json", "view"):
            fmt = arg[9:]
    return render.Renderer("tdd", fmt=fmt)


def _run(argv: list[str]) -> int:
    opts, rest = _split(argv)

    wants_output = (
        opts["reqs"] or opts["porcelain"] or opts["defaults"] or opts.get("version")
    )
    if opts.get("help") or (not rest and not wants_output):
        print(USAGE, end="")
        return 0

    dir_ = paths.tdd_dir(opts["dir"])
    out = _renderer("tdd", opts["format"], opts["verbose"])
    out.debug(f"tdd dir: {dir_}")

    if opts.get("version"):
        found = version_mod.current(dir_)
        return out.ok(f"tdd {found}", version=found)
    if opts["reqs"]:
        return reqs_mod.check(rest[0] if rest else None, out)
    # Plumbing for the tdd shell function: plain lines, never events.
    if opts["porcelain"]:
        return _porcelain(dir_, "--demo" in rest)
    if opts["defaults"]:
        return _defaults(dir_, rest)

    word, tool_argv = rest[0], rest[1:]

    if word == "doctor":
        return _doctor(dir_, _builtin_opts(word, tool_argv, opts))
    if word == "info":
        return _info(dir_, _builtin_opts(word, tool_argv, opts))

    try:
        return dispatch_mod.dispatch(dir_, word, tool_argv, out)
    except catalog_mod.NotInitialized as exc:
        return out.error(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
