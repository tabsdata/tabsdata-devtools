#
# Copyright 2026 Tabsdata Inc.
#

"""Checking external binary requirements. Standard library only.

Reqs are read from the catalog rather than the source tree, so this works
before tdd-install and from a wheel install -- checking a fresh machine's
prerequisites is exactly when no environment exists yet.
"""

from __future__ import annotations

import os
import pathlib
import re
import shutil
import subprocess

from . import catalog as catalog_mod
from . import render

#: Which shell family's requirements a command is checked against. Each loader
#: exports it, so `tdd --reqs` under PowerShell does not ask for the POSIX
#: half's `jq` and `awk`. Unset -- nothing sourced, a bare `tdd-exe` -- means
#: the platform's own: PowerShell on Windows, where no POSIX shell is assumed;
#: the POSIX half elsewhere, which is what a machine without pwsh has.
FAMILY_ENV = "_TDD_SHELL_FAMILY"
DEFAULT_FAMILY = "powershell" if os.name == "nt" else "unix"


def shell_family() -> str:
    return os.environ.get(FAMILY_ENV, "").strip() or DEFAULT_FAMILY


def _for_family(value: list | dict, family: str) -> list[str]:
    if isinstance(value, dict):
        return value.get(family, value.get(DEFAULT_FAMILY, []))
    return value


def entry_required(entry: dict, family: str) -> list[str]:
    """A catalog entry's required binaries. One list for a tool with no family
    file; per family for a shell command, whose halves' helpers differ, and for
    a tool that declares bin-reqs.<family>.txt."""
    return _for_family(entry.get("required", []), family)


def entry_optional(entry: dict, family: str) -> list[str]:
    """A catalog entry's optional binaries: allowed and reported, never
    required up front -- the one a run uses is checked where it is used."""
    return _for_family(entry.get("optional", []), family)


# Version managers whose shims stand in for every program any of their
# versions ever installed: the shim exists on PATH whether or not the CURRENT
# version has the program, so finding it proves nothing. Each answers
# `<manager> which <program>` with the real path, or fails.
SHIM_MANAGERS = ("pyenv", "asdf", "mise")
_SHIM_MAX_BYTES = 4096


def shim_manager(path: str) -> str | None:
    """The manager behind `path` when it is one of their shims -- a small script
    whose job is `<manager> exec <program>` -- else None. The signature is the
    manager's name followed by `exec`: Homebrew's own `pyenv` launcher is a
    small script too, but it `exec`s pyenv, it does not ask pyenv to exec."""
    try:
        file = pathlib.Path(path)
        if file.stat().st_size > _SHIM_MAX_BYTES:
            return None
        text = file.read_text(errors="replace")
    except OSError:
        return None
    if not text.startswith("#!"):
        return None
    for manager in SHIM_MANAGERS:
        if re.search(rf'(^|[\s"/]){manager}"?\s+(exec|x)\b', text, re.MULTILINE):
            return manager
    return None


def resolve(binary: str) -> tuple[str | None, str]:
    """(the real path, or None when missing; a note). A binary found through a
    shim counts only if its manager wires it to a real program; the note says
    so either way (`pyenv shim`, or why it is not wired)."""
    found = shutil.which(binary)
    if found is None:
        return None, ""
    manager = shim_manager(found)
    if manager is None or shutil.which(manager) is None:
        return found, ""
    cp = subprocess.run(
        [manager, "which", binary], check=False, capture_output=True, text=True
    )
    out = (cp.stdout or "").strip()
    if cp.returncode == 0 and out:
        real = out.splitlines()[-1]
        # A manager that answers with a shim (its own, or one that shadows the
        # program on PATH) has not found a real program either.
        if real != found and shim_manager(real) is None:
            return real, f"{manager} shim"
        return (
            None,
            f"{manager} shim at {found} is not wired: {manager} which resolves to a shim ({real})",
        )
    why = ((cp.stderr or "").strip() or out or f"{manager} which failed").splitlines()[
        0
    ]
    return None, f"{manager} shim at {found} is not wired: {why}"


def missing_details(binaries: list[str]) -> list[tuple[str, str]]:
    """The declared binaries not usable from the ambient PATH, each with why
    (empty when simply absent) -- for a message that lists them one per line."""
    out = []
    for binary in binaries:
        path, note = resolve(binary)
        if path is None:
            out.append((binary, note))
    return out


def missing(binaries: list[str]) -> list[str]:
    """The declared binaries not usable from the ambient PATH -- on purpose the
    ambient one: a req is something the machine must already provide, not
    something a toolset venv can supply. A shim that its manager does not wire
    is reported with the reason."""
    out = []
    for binary in binaries:
        path, note = resolve(binary)
        if path is None:
            out.append(f"{binary} ({note})" if note else binary)
    return out


def check(tool: str | None, out: render.Renderer, *, summary: bool = False) -> int:
    """Every declared binary, resolved: per command (who needs what), or with
    `summary` one line per binary (what the machine must provide)."""
    catalog = catalog_mod.shipped()
    out.debug(f"catalog: {catalog_mod.shipped_path()}")
    # Both halves declare binaries the same way; the shell ones are marked so
    # the report reads like `tdd help`.
    entries = {name: (entry, "") for name, entry in catalog["tools"].items()}
    entries.update(
        (name, (entry, " (shell)")) for name, entry in catalog.get("shell", {}).items()
    )

    if tool is not None:
        if tool not in entries:
            return out.error(f"unknown tool or shell command {tool!r}")
        selected = {tool: entries[tool]}
    else:
        selected = entries

    family = shell_family()
    out.debug(f"shell family: {family}")
    if summary:
        return _summary(selected, tool, family, out)
    missing: list[str] = []
    checked = 0
    for name, (entry, label) in sorted(selected.items()):
        reqs = entry_required(entry, family)
        _report_optional(name, label, entry_optional(entry, family), out)
        if not reqs:
            out.info(f"{name}{label}: no external requirements", command_name=name)
            continue
        for binary in reqs:
            found, note = resolve(binary)
            checked += 1
            if found:
                out.info(
                    f"{name}{label}: [ok] {binary} -> {found}"
                    + (f" ({note})" if note else ""),
                    command_name=name,
                    binary=binary,
                    path=found,
                    **({"via": note} if note else {}),
                )
            else:
                missing.append(f"{name}: {binary}" + (f" ({note})" if note else ""))
                out.warn(
                    f"{name}{label}: [missing] {binary}"
                    + (f" ({note})" if note else ""),
                    command_name=name,
                    binary=binary,
                    **({"why": note} if note else {}),
                )
    if missing:
        return out.error(
            f"{len(missing)} required binaries missing: {', '.join(missing)}",
            missing=missing,
        )
    return out.ok(f"all {checked} required binaries present", checked=checked)


def _report_optional(
    name: str,
    label: str,
    optional: list[str],
    out: render.Renderer,
) -> None:
    """Optional binaries, said as information: present or not, never missing."""
    for binary in optional:
        found, note = resolve(binary)
        state = f"-> {found}" if found else "not installed"
        out.info(
            f"{name}{label}: [optional] {binary} {state}"
            + (f" ({note})" if note else ""),
            command_name=name,
            binary=binary,
            optional=True,
            **({"path": found} if found else {}),
        )


def _summary(
    selected: dict[str, tuple[dict, str]],
    tool: str | None,
    family: str,
    out: render.Renderer,
) -> int:
    # One line per binary, however many commands declare it: the question is
    # what the machine has to provide, and jq needed by four commands is one
    # jq to install. Who needs it travels in the JSON fields (`needed_by`).
    needed_by: dict[str, list[str]] = {}
    used_by: dict[str, list[str]] = {}
    for name, (entry, label) in sorted(selected.items()):
        for binary in entry_required(entry, family):
            needed_by.setdefault(binary, []).append(f"{name}{label}")
        for binary in entry_optional(entry, family):
            used_by.setdefault(binary, []).append(f"{name}{label}")
    optional_only = set(used_by) - set(needed_by)
    if not needed_by and not optional_only:
        what = tool if tool is not None else "anything"
        return out.ok(f"{what}: no external requirements", checked=0)
    missing: list[str] = []
    # One sorted list, each binary once: required ones [ok]/[missing], an
    # optional one -- needed by none of the selected -- said as [optional].
    for binary in sorted(set(needed_by) | optional_only):
        found, note = resolve(binary)
        via = f" ({note})" if note else ""
        if binary in optional_only:
            out.info(
                f"[optional] {binary} "
                + (f"-> {found}{via}" if found else "not installed"),
                binary=binary,
                optional=True,
                used_by=used_by[binary],
                **({"path": found} if found else {}),
            )
        elif found:
            out.info(
                f"[ok] {binary} -> {found}{via}",
                binary=binary,
                path=found,
                needed_by=needed_by[binary],
                **({"via": note} if note else {}),
            )
        else:
            missing.append(f"{binary}{via}")
            out.warn(
                f"[missing] {binary}{via}",
                binary=binary,
                needed_by=needed_by[binary],
                **({"why": note} if note else {}),
            )
    checked = len(needed_by)
    if missing:
        return out.error(
            f"{len(missing)} of {checked} required binaries missing: "
            f"{', '.join(missing)}",
            missing=missing,
        )
    return out.ok(f"all {checked} required binaries present", checked=checked)
