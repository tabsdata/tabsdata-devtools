#
# Copyright 2026 Tabsdata Inc.
#

"""Secret providers (``secrets --set <PROVIDER>:<REF>``).

A provider fetches a set of named secrets from an external store and returns them
as an ordered ``{<NAME>: <value>}`` dict, where each ``NAME`` follows the
``<PREFIX>__<KEY>`` convention a system's env-sourced create options read.
``--set`` selects a provider by scheme:

    1p:<VAULT>      1Password, via the ``op`` CLI  (see :mod:`.secret_1p`)

Adding a provider (hashicorp, ghsecrets, …) is just dropping a
``secrets_<scheme>.py`` module exposing ``fetch(ref) -> dict[str, str]`` and
registering its scheme in ``_PROVIDERS`` below.
"""

from __future__ import annotations

import importlib
import json
import shlex

from . import resources
from .errors import ToolError

# scheme -> module (relative to this package) implementing `fetch(ref)`.
_PROVIDERS: dict[str, str] = {
    "1p": "secrets_1p",
}

OUT_FORMATS = ("json", "export", "unset")

#: The platforms an export is written for. macOS and Linux share one form,
#: `unix`: sh export lines. Windows gets a PowerShell file to dot-source.
PLATFORMS = ("macos", "linux", "windows")
UNIX_PLATFORMS = ("macos", "linux")
DEFAULT_PLATFORM = "macos"

#: This package, whose resources hold the Windows export's template.
PACKAGE = "tabsdata_dev.common.core"
#: The quote characters PowerShell reads in a single-quoted string -- ASCII
#: and the four typographic ones -- each written twice to stand for itself.
_PS_QUOTES = "'\u2018\u2019\u201a\u201b"


def _export_unix(secrets: dict[str, str]) -> str:
    """sh export lines, each value quoted for sh: what `tdd env` evaluates."""
    return "\n".join(
        f"export {name}={shlex.quote(str(v))}" for name, v in secrets.items()
    )


def export_lines(variables: dict[str, str], platform: str = DEFAULT_PLATFORM) -> str:
    """Lines that set `variables` in the session that evaluates them: sh
    `export` lines on macOS and Linux, PowerShell `$env:` lines on Windows
    (`... | Invoke-Expression`). Lines, not a file: what a command prints for
    its caller to apply in place."""
    if platform in UNIX_PLATFORMS:
        return _export_unix(variables)
    if platform == "windows":
        return "\n".join(
            f"$env:{name} = {_ps_quote(str(v))}" for name, v in variables.items()
        )
    raise ToolError(f"unknown platform {platform!r} ({', '.join(PLATFORMS)})")


def _export_windows(secrets: dict[str, str]) -> str:
    """A PowerShell file of $env: lines, for a machine without 1Password to
    dot-source; the template says what the file is, since it travels."""
    variables = [(name, _ps_quote(str(v))) for name, v in secrets.items()]
    text = resources.render(PACKAGE, "secrets.ps1", variables=variables)
    return text.rstrip("\n")


def _ps_quote(value: str) -> str:
    """`value` as a PowerShell single-quoted string: nothing in it expands ($,
    backtick), it may span lines, and only quote characters need escaping."""
    return "'" + "".join(c * 2 if c in _PS_QUOTES else c for c in value) + "'"


# The personal key that encrypts the system and domain descriptors: its
# variable, and the shortest value accepted. Here rather than in common-systems
# because `_1p fetch` reads it from 1Password and checks it, in a toolset that
# carries common-core only; `common.systems.crypto` enforces the same minimum.
CRYPTO_KEY_ENV = "_TDD_CRYPTO_KEY"
CRYPTO_KEY_MIN_LEN = 12

# Set alongside the fetched secrets: the distinct env prefixes (the ``<PREFIX>``
# part of each ``<PREFIX>__<KEY>`` name) that now have credentials — it names the
# systems the secrets populate. Part of the ``TD_BACKENDS_*`` env family.
SYSTEMS_ENV = "_TDD_SYSTEMS"


def _prefixes(secrets: dict[str, str]) -> list[str]:
    """Distinct ``<PREFIX>`` values (the part before the first ``__``) across the
    fetched secret names, in first-seen order. Ignores the synthetic SYSTEMS_ENV
    entry (so it stays idempotent)."""
    out: list[str] = []
    for name in secrets:
        if name == SYSTEMS_ENV:
            continue
        prefix = name.split("__", 1)[0]
        if prefix and prefix not in out:
            out.append(prefix)
    return out


def with_systems_var(secrets: dict[str, str]) -> dict[str, str]:
    """`secrets` plus a synthetic ``_TDD_SYSTEMS`` entry listing the
    populated env prefixes (space-separated), so a consumer knows which systems
    have credentials set. Skipped when there are no prefixes; idempotent."""
    prefixes = _prefixes(secrets)
    if not prefixes:
        return secrets
    return {**secrets, SYSTEMS_ENV: " ".join(prefixes)}


def parse_ref(ref_arg: str) -> tuple[str, str]:
    """Split a ``--set`` value ``<scheme>:<ref>`` into (scheme, ref)."""
    scheme, sep, ref = ref_arg.partition(":")
    scheme, ref = scheme.strip(), ref.strip()
    if not sep or not scheme or not ref:
        raise ToolError(
            f"--set expects <PROVIDER>:<REF> (e.g. 1p:dev_xp), got {ref_arg!r}"
        )
    return scheme, ref


def _load_provider(scheme: str):
    modname = _PROVIDERS.get(scheme)
    if modname is None:
        raise ToolError(
            f"unknown secret provider {scheme!r} in --set "
            f"(supported: {', '.join(sorted(_PROVIDERS))})"
        )
    return importlib.import_module(f".{modname}", __package__)


def read_field(scheme: str, vault: str, item: str, field: str) -> str:
    """One named secret from a provider (``1p`` only, today): the personal-vault
    case, where the caller knows exactly which item and field it wants."""
    provider = _load_provider(scheme)
    reader = getattr(provider, "read_field", None)
    if reader is None:
        raise ToolError(f"secret provider {scheme!r} cannot read a single field")
    return reader(vault, item, field)


def fetch(ref_arg: str) -> dict[str, str]:
    """Resolve ``--set <PROVIDER>:<REF>`` to an ordered dict of secret env vars.

    Dispatches to the provider module registered for ``<PROVIDER>``; the ref is
    provider-specific (a vault name for ``1p``, etc.)."""
    scheme, ref = parse_ref(ref_arg)
    return _load_provider(scheme).fetch(ref)


def render(
    secrets: dict[str, str],
    out: str,
    platform: str = DEFAULT_PLATFORM,
) -> str:
    """Render fetched secrets as a JSON dict / an export / ``unset`` lines. An
    export is written for `platform`: sh ``export`` lines on macOS and Linux,
    a PowerShell file of ``$env:`` lines on Windows.

    Names are already valid env-var names (the providers normalise them)."""
    if out == "json":
        return json.dumps(secrets, indent=2)
    if out == "export":
        if platform in UNIX_PLATFORMS:
            return _export_unix(secrets)
        if platform == "windows":
            return _export_windows(secrets)
        raise ToolError(f"unknown platform {platform!r} ({', '.join(PLATFORMS)})")
    if out == "unset":
        return "\n".join(f"unset {name}" for name in secrets)
    raise ToolError(f"unknown format {out!r} (expected {'|'.join(OUT_FORMATS)})")
