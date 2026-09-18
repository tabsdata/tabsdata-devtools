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
BIN_REQS = "bin-reqs.txt"

#: The shell families: each one's command-file suffix and its shared helper
#: file, which is not a command. A family is the shell the user is in, not the
#: operating system they are on -- PowerShell 7 runs on macOS, Linux and
#: Windows. Mirrors `tabsdata_dev.shell`, which this package may not import:
#: `-tdd` has no dependencies, forever.
SHELL_FAMILIES = {"unix": ".sh", "powershell": ".ps1"}
SHELL_COMMON = {"unix": "common.sh", "powershell": "common.ps1"}

#: The family whose summaries and command set the others are held to.
SHELL_CANONICAL = "unix"

# `tdd_fn_register <name> "<summary>"`, as the command files write it. One
# regex serves both families: the call is spelled the same in sh and in
# PowerShell, which is what lets each be checked against the other.
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


def shell_family(root: pathlib.Path, family: str) -> dict[str, dict]:
    """One family's commands: the file that registers each, its summary and the
    binaries it declares.

    A `<file>.bin-reqs.txt` beside `<file><suffix>` applies to every command
    that file registers; `common.bin-reqs.txt` -- what the family's shared
    helpers themselves need -- applies to all of them, which is why the two
    families' requirements differ: the POSIX half builds its JSON with `jq` and
    lays out its help with `awk`, and PowerShell needs neither.
    """
    suffix = SHELL_FAMILIES[family]
    common = SHELL_COMMON[family]
    scripts = root / "packages" / SHELL_DIST / "scripts" / family
    if not scripts.is_dir():
        raise LayoutError(f"no {family} shell scripts at {scripts}")
    common_reqs = parse_bin_reqs(scripts / f"{common[: -len(suffix)]}.{BIN_REQS}")
    found: dict[str, dict] = {}
    for script in sorted(scripts.glob(f"*{suffix}")):
        if script.name == common:
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
                    f"duplicate shell command {name!r} in {family}: "
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
        if not (scripts / f"{stem}{suffix}").is_file():
            raise LayoutError(f"{reqs_file}: no {stem}{suffix} beside it to apply to")
    return found


def shell_commands(root: pathlib.Path) -> dict[str, dict]:
    """Shell commands across every family, read from the shell package.

    The registry each loader builds while sourcing is the runtime truth; this
    reads the same files statically so the catalog can carry their reqs -- for
    `tdd --reqs` before anything is sourced -- and their names, so no Python
    tool can be given a name a shell function would answer to first.

    Every family must register the same commands with the same summaries: they
    are one command each, written twice, and `tdd help` reads the same whichever
    shell the user is in. The file and the requirements are the family's own, so
    both are recorded per family.
    """
    families = {f: shell_family(root, f) for f in SHELL_FAMILIES}
    canonical = families[SHELL_CANONICAL]
    for family, commands in families.items():
        if family == SHELL_CANONICAL:
            continue
        missing = sorted(set(canonical) - set(commands))
        extra = sorted(set(commands) - set(canonical))
        if missing or extra:
            raise LayoutError(
                f"the {family} shell commands do not match {SHELL_CANONICAL}: "
                + ", ".join(
                    [f"missing {m}" for m in missing]
                    + [f"only here: {e}" for e in extra]
                )
                + f" -- every command exists in both, with {SHELL_FAMILIES[family]} "
                "and .sh spellings of the same thing"
            )
        for name, entry in commands.items():
            if entry["summary"] != canonical[name]["summary"]:
                raise LayoutError(
                    f"{name}: the {family} summary differs from {SHELL_CANONICAL}'s; "
                    "`tdd help` must read the same in either shell"
                )
    return {
        name: {
            "summary": entry["summary"],
            "files": {f: families[f][name]["file"] for f in families},
            "reqs": {f: families[f][name]["reqs"] for f in families},
        }
        for name, entry in canonical.items()
    }


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
        # `[tool.tdd] disabled = true` comments a tool out: the package stays
        # in the tree, tests and all, and the generator treats it as absent
        # -- no catalog entry, no toolset membership, no env, no config file.
        # Skipped before any check, so a parked package need not be complete.
        if bool(tdd_cfg.get("disabled", False)):
            continue
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
                files = ", ".join(sorted(shell[command]["files"].values()))
                raise LayoutError(
                    f"{dist}: tool name {command!r} is already a shell command "
                    f"({files})"
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
