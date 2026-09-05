#
# Copyright 2026 Tabsdata Inc.
#

"""Scanning the source repo for tools, deps bundles, shell commands and their
groupings.

Standard library only -- bin-reqs.txt is plain text, shell scripts are matched
with a regex, and pyproject.toml is read with tomllib, so nothing here needs a
third-party parser.
"""

from __future__ import annotations

import pathlib
import re
import tomllib

from . import paths

TOOL_PREFIX = "tabsdata-dev-tool-"
DEPS_PREFIX = "tabsdata-dev-deps-"
TOOLSET_PREFIX = "tabsdata-dev-toolset-"
COMMON_PREFIX = "tabsdata-dev-common-"
SHELL_DIST = "tabsdata-dev-shell"
SHELL_SCRIPTS = "scripts/unix"
SHELL_COMMON = "common.sh"  # the shared helpers, not a command file
BIN_REQS = "bin-reqs.txt"

# `tdd_fn_register <name> "<summary>"`, as the shell files write it.
_REGISTER = re.compile(r'^tdd_fn_register\s+(?P<name>\S+)\s+"(?P<summary>[^"]*)"')


class LayoutError(Exception):
    pass


def parse_bin_reqs(path: pathlib.Path) -> list[str]:
    """One bare binary name per line. Blank lines and # comments ignored."""
    if not path.is_file():
        return []
    out = []
    for lineno, raw in enumerate(path.read_text().splitlines(), 1):
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if len(line.split()) != 1 or "/" in line:
            raise LayoutError(
                f"{path}:{lineno}: expected a bare binary name, got {line!r}"
            )
        out.append(line)
    return out


def shell_commands(root: pathlib.Path) -> dict[str, dict]:
    """Shell commands and their declared binaries, read from the shell package.

    The registry tdd-source.sh builds while sourcing is the runtime truth; this
    reads the same files statically so the catalog can carry their reqs -- for
    `tdd --reqs` before anything is sourced -- and their names, so no Python
    tool can be given a name the shell function would answer to first.

    A `<file>.bin-reqs.txt` beside `<file>.sh` applies to every command that
    file registers; `common.bin-reqs.txt` -- what common.sh itself needs --
    applies to all of them.
    """
    scripts = root / "packages" / SHELL_DIST / SHELL_SCRIPTS
    common_reqs = parse_bin_reqs(scripts / f"{SHELL_COMMON[:-3]}.{BIN_REQS}")
    found: dict[str, dict] = {}
    for script in sorted(scripts.glob("*.sh")):
        if script.name == SHELL_COMMON:
            continue
        own = parse_bin_reqs(script.with_name(f"{script.stem}.{BIN_REQS}"))
        reqs = common_reqs + [r for r in own if r not in common_reqs]
        registered = 0
        for raw in script.read_text().splitlines():
            match = _REGISTER.match(raw)
            if match is None:
                continue
            name = match["name"]
            if name in found:
                raise LayoutError(
                    f"duplicate shell command {name!r}: "
                    f"{found[name]['file']} and {script.name}"
                )
            found[name] = {
                "file": script.name,
                "summary": match["summary"],
                "reqs": reqs,
            }
            registered += 1
        if not registered:
            raise LayoutError(f"{script}: registers no command")
    for reqs_file in sorted(scripts.glob(f"*.{BIN_REQS}")):
        stem = reqs_file.name[: -len(f".{BIN_REQS}")]
        if not (scripts / f"{stem}.sh").is_file():
            raise LayoutError(f"{reqs_file}: no {stem}.sh beside it to apply to")
    return found


def discover(root: pathlib.Path) -> dict:
    """Return {"tools": {...}, "toolsets": {name: [dist, ...]}, "shell": {...}}."""
    pkgs = root / "packages"
    if not pkgs.is_dir():
        raise LayoutError(f"no packages/ directory under {root}")

    tools: dict[str, dict] = {}
    toolsets: dict[str, list[str]] = {}
    shell = shell_commands(root)

    for pyproject in sorted(pkgs.glob(TOOL_PREFIX + "*/pyproject.toml")):
        doc = tomllib.loads(pyproject.read_text())
        data = doc["project"]
        dist = data["name"]
        deps = data.get("dependencies", [])
        # `[tool.tdd] hidden = true` marks plumbing another tool dispatches to
        # (a sibling in a second toolset): dispatchable, but left out of
        # `tdd help` -- a listing concern only.
        tdd_cfg = doc.get("tool", {}).get("tdd", {})
        hidden = bool(tdd_cfg.get("hidden", False))
        # `[tool.tdd] launcher = true` marks a tool that owns no options at all:
        # every argument belongs to the program it runs (the one exception to the
        # CLI guidelines), so it has no `config` action and no config file.
        launcher = bool(tdd_cfg.get("launcher", False))
        # The common-* packages this tool uses: they join its toolset, and only
        # its toolset -- a heavy shared library must not land in every env.
        commons = sorted(
            re.split(r"[<>=!~\[ ;]", d, maxsplit=1)[0]
            for d in deps
            if d.startswith(COMMON_PREFIX)
        )

        bundles = [d for d in deps if d.startswith(DEPS_PREFIX)]
        if len(bundles) != 1:
            raise LayoutError(
                f"{dist}: must depend on exactly one {DEPS_PREFIX}* package, "
                f"found {bundles or 'none'}"
            )
        toolset = bundles[0][len(DEPS_PREFIX) :]

        scripts = data.get("scripts", {})
        if not scripts:
            raise LayoutError(f"{dist}: declares no [project.scripts] entry point")

        reqs = parse_bin_reqs(pyproject.parent / BIN_REQS)

        for command in scripts:
            if command in paths.RESERVED:
                raise LayoutError(
                    f"{dist}: tool name {command!r} is a reserved tdd word"
                )
            if command in shell:
                # The tdd function consults its shell registry first, so the
                # tool would exist but never be reachable.
                raise LayoutError(
                    f"{dist}: tool name {command!r} is already a shell command "
                    f"({shell[command]['file']})"
                )
            if command in tools:
                raise LayoutError(
                    f"duplicate tool name {command!r}: "
                    f"{tools[command]['package']} and {dist}"
                )
            tools[command] = {
                "toolset": toolset,
                "package": dist,
                "summary": data.get("description", ""),
                "reqs": reqs,
                "launcher": launcher,
                "hidden": hidden,
                "commons": commons,
            }
        toolsets.setdefault(toolset, []).append(dist)

    pythons: dict[str, str] = {}
    for name in toolsets:
        bundle = pkgs / (DEPS_PREFIX + name)
        if not bundle.is_dir():
            raise LayoutError(f"missing deps bundle {bundle.name} for toolset {name}")
        # `[tool.tdd] python = "3.12"` in a bundle pins the toolset's interpreter
        # minor: drivers without wheels for the newest CPython are the usual
        # reason a toolset cannot ride the default interpreter.
        cfg_path = bundle / "pyproject.toml"
        cfg = tomllib.loads(cfg_path.read_text()) if cfg_path.is_file() else {}
        python = cfg.get("tool", {}).get("tdd", {}).get("python")
        if python:
            if not re.fullmatch(r"3\.\d+", str(python)):
                raise LayoutError(
                    f"{bundle.name}: [tool.tdd] python must be like 3.12, got {python!r}"
                )
            pythons[name] = str(python)

    return {"tools": tools, "toolsets": toolsets, "shell": shell, "python": pythons}


def common_packages(root: pathlib.Path) -> list[str]:
    return sorted(
        p.name for p in (root / "packages").glob(COMMON_PREFIX + "*") if p.is_dir()
    )
