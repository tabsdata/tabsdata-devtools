#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd _1p`` -- what tdd fetches from and pushes to 1Password.

    tdd _1p fetch [--crypto [1p:VAULT] [--item ITEM] [--field FIELD]]
                  [--secrets [1p:VAULT]] [--pypi-twine [1p:VAULT]]
                  [--format export|json|view]
    tdd _1p push --vault 1p:VAULT --entry PATH|-

``--crypto`` reads the one field that is the descriptor key
(``_TDD_CRYPTO_KEY``) out of a personal vault; ``--secrets`` sweeps a shared
vault, every item's fields becoming ``<ITEM>__<FIELD>`` variables, plus
``_TDD_SYSTEMS``, the list of the prefixes it set; ``--pypi-twine`` reads the
package-upload credentials next to the key and names them as twine reads them,
``TWINE_USERNAME``/``TWINE_PASSWORD``. Any mix, one call: the result is
``export`` lines, printed as the outcome for the caller to apply.

This is plumbing for ``tdd env set --crypto/--secrets/--pypi-twine``. A Python process
cannot change the shell that runs it, so ``env`` -- a shell command -- runs this
and applies the lines, and nothing is written to disk. The providers live in
``common.core.secrets``; this tool only chooses what to read and checks it.

``push`` files one item in a vault, replacing what is filed under its title
(delete, then create: a create alone duplicates) -- the other end of
``tdd system 1p-template`` and ``tdd system info --format 1p``, which write the
item. It was ``tdd system 1p-set``; filing an item touches no system.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

from tabsdata_dev.common.core import cli, render, secrets, secrets_1p
from tabsdata_dev.common.core.errors import ToolError

NAME = "_1p"
DESCRIPTION = (
    "fetches the crypto key and secrets from 1Password (for tdd env) and pushes "
    "items to it"
)

FETCH = "fetch"
PUSH = "push"
ACTIONS = (FETCH, PUSH)
#: `fetch`'s own rendering and the default: the lines a shell applies.
FMT_EXPORT = "export"
# Where fetch reads from when --crypto / --secrets are given alone: the
# Employee vault every user has (item DevSecrets, the field that item has
# always had) and the team's shared vault. Literals: no variable of the
# environment chooses a vault. `tdd env` passes the vaults it keeps in env.toml,
# the same two unless changed there.
DEFAULT_CRYPTO_VAULT = "1p:Employee"
DEFAULT_SECRETS_VAULT = "1p:dev_xp"
DEFAULT_CRYPTO_ITEM = "DevSecrets"
DEFAULT_CRYPTO_FIELD = "TD_BACKENDS_CRYPTO_KEY"
# The PyPI upload credentials live in the crypto key's item, under names of
# their own; exported under the names twine reads, so `twine upload` (and
# `uv publish`'s twine fallback) needs nothing else.
TWINE_ITEM = DEFAULT_CRYPTO_ITEM
TWINE_FIELDS = (
    ("PYPI_TWINE_USERNAME", "TWINE_USERNAME"),
    ("PYPI_TWINE_PASSWORD", "TWINE_PASSWORD"),
)


def _ref(option: str, value: str) -> tuple[str, str]:
    """(provider, vault) of a provider ref such as ``1p:Employee``."""
    scheme, sep, vault = value.partition(":")
    if not sep or not scheme.strip() or not vault.strip():
        raise ToolError(
            f"{option} takes a provider ref, 1p:VAULT (e.g. 1p:dev_xp), got {value!r}"
        )
    return scheme.strip(), vault.strip()


def crypto_key(ref: str, item: str, field: str) -> str:
    """The descriptor key at `item`/`field` of the vault `ref` names, refused
    when it is shorter than the crypto module accepts -- better here, with
    where it came from, than at the first descriptor it fails to open."""
    scheme, vault = _ref("--crypto", ref)
    value = secrets.read_field(scheme, vault, item, field)
    if len(value) < secrets.CRYPTO_KEY_MIN_LEN:
        raise ToolError(
            f"{secrets.CRYPTO_KEY_ENV} from {scheme}:{vault}/{item}/{field} is "
            f"{len(value)} characters; it must be at least "
            f"{secrets.CRYPTO_KEY_MIN_LEN}"
        )
    return value


def read_entry(entry: str) -> dict:
    """The item JSON `--entry` names: a file, or ``-`` for stdin, reduced to
    what a create may carry (`secrets_1p.for_upload`), so a whole `op item get
    --format=json` can be handed straight back.

    Refuses anything that is not an item, by the three keys `op item create`
    needs -- a title to file it under, a category to shape it, and the fields
    themselves. Better here than as op's own error after the delete has already
    happened."""
    if entry == "-":
        # Decode the pipe ourselves: sys.stdin's encoding follows the locale, so
        # an item read under LANG=C would not survive a non-ASCII value.
        text = sys.stdin.buffer.read().decode("utf-8")
        where = "stdin"
    else:
        try:
            text = pathlib.Path(entry).expanduser().read_text(encoding="utf-8")
        except OSError as exc:
            raise ToolError(f"cannot read --entry {entry}: {exc}")
        where = entry
    try:
        item = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ToolError(f"{where} is not valid JSON: {exc}")
    if not isinstance(item, dict):
        raise ToolError(f"{where} must be one 1Password item (a JSON object)")
    missing = [k for k in secrets_1p.UPLOAD_KEYS if not item.get(k)]
    if missing:
        raise ToolError(
            f"{where} is not a 1Password item: no {', '.join(missing)} "
            f"(`tdd system 1p-template --type TYPE` writes one)"
        )
    return secrets_1p.for_upload(item)


def _vault(option: str, value: str) -> str:
    """The vault a `1p:VAULT` ref names; filing speaks 1Password only."""
    scheme, vault = _ref(option, value)
    if scheme != "1p":
        raise ToolError(f"{option}: only 1p:VAULT files an item, got {value!r}")
    return vault


def _push(args: argparse.Namespace, out: render.Renderer) -> int:
    vault = _vault("--vault", args.vault)  # refused before the entry is read
    item = read_entry(args.entry)
    title = str(item["title"])
    out.info(f"pushing '{title}' to {args.vault}")
    replaced, item_id = secrets_1p.set_item(vault, item)
    return out.ok(
        f"{'replaced' if replaced else 'created'} '{title}' in {args.vault}"
        + (f" ({item_id})" if item_id else "")
        + (" -- the item it replaced is in Recently Deleted" if replaced else ""),
        vault=vault,
        title=title,
        replaced=replaced,
        id=item_id,
    )


def _fetch(args: argparse.Namespace, out: render.Renderer) -> int:
    if not args.crypto and not args.secrets and not args.pypi_twine:
        raise ToolError(
            "nothing to fetch: pass --crypto [1p:VAULT], --secrets [1p:VAULT] "
            "and/or --pypi-twine [1p:VAULT]"
        )
    if (args.item or args.field) and not args.crypto:
        raise ToolError("--item and --field say where the crypto key is; pass --crypto")
    if args.secrets:
        _ref("--secrets", args.secrets)  # refused before anything is read
    if args.pypi_twine:
        _ref("--pypi-twine", args.pypi_twine)
    found: dict[str, str] = {}
    if args.crypto:
        item = args.item or DEFAULT_CRYPTO_ITEM
        field = args.field or DEFAULT_CRYPTO_FIELD
        out.debug(f"reading {args.crypto}/{item}/{field}")
        found[secrets.CRYPTO_KEY_ENV] = crypto_key(args.crypto, item, field)
    if args.pypi_twine:
        scheme, vault = _ref("--pypi-twine", args.pypi_twine)
        for field, name in TWINE_FIELDS:
            out.debug(f"reading {args.pypi_twine}/{TWINE_ITEM}/{field}")
            found[name] = secrets.read_field(scheme, vault, TWINE_ITEM, field)
    if args.secrets:
        out.debug(f"reading every item of {args.secrets}")
        found.update(secrets.with_systems_var(secrets.fetch(args.secrets)))
    names = list(found)
    if args.format == FMT_EXPORT:
        # The outcome IS the lines to apply: `tdd env` evaluates what comes out.
        return out.ok(secrets.render(found, "export"), names=names)
    summary = f"fetched {len(names)} variable(s): {' '.join(names)}"
    if args.format == "json":
        # JSON is asked for by name, by a program: the values travel, as they do
        # in the export lines.
        return out.ok(summary, names=names, values=found)
    # view is for a person at a terminal: what was read, never the values.
    return out.ok(summary, names=names)


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action not in ACTIONS:
        raise ToolError(f"a subcommand is required: {', '.join(ACTIONS)} (see --help)")
    if args.action == PUSH:
        return _push(args, out)
    return _fetch(args, out)


def _common(
    sub: argparse.ArgumentParser, formats: dict[str, str], default: str
) -> None:
    """--format/--verbose after the subcommand word too, with the formats that
    subcommand renders. SUPPRESS so an unused copy does not overwrite what was
    given before the word; the top-level default (export) is what `fetch`
    takes, and `push`, which has nothing to export, reads it as view."""
    sub.add_argument(
        "--format",
        choices=tuple(formats),
        default=argparse.SUPPRESS,
        help="; ".join(f"{k}: {v}" for k, v in formats.items())
        + f" (default: {default})",
    )
    sub.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=argparse.SUPPRESS,
        help="show debug events too",
    )


def configure(p: argparse.ArgumentParser) -> None:
    p.epilog = (
        f"examples: tdd {NAME} {FETCH} --crypto --secrets\n"
        f"          tdd system 1p-template --type s3 | tdd {NAME} {PUSH} "
        "--vault 1p:dev_xp --entry -"
    )
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    fetch = sub.add_parser(
        FETCH,
        help="fetches the crypto key, a vault's secrets and/or the PyPI upload "
        "credentials, as export lines",
        description=(
            "Fetches the descriptor crypto key (--crypto), every secret of a "
            "shared vault (--secrets) and/or the PyPI upload credentials "
            "(--pypi-twine) from 1Password. By default (--format export) "
            "they are printed as export lines, the outcome of the command, for a "
            "shell to apply -- `tdd env set --crypto --secrets` does; view names "
            "what was fetched without the values, json carries them."
        ),
    )
    fetch.add_argument(
        "--crypto",
        nargs="?",
        const=DEFAULT_CRYPTO_VAULT,
        default=None,
        metavar="1p:VAULT",
        help=f"fetch {secrets.CRYPTO_KEY_ENV} from this vault (alone: "
        f"{DEFAULT_CRYPTO_VAULT}); at least {secrets.CRYPTO_KEY_MIN_LEN} characters",
    )
    fetch.add_argument(
        "--item",
        default=None,
        metavar="ITEM",
        help=f"--crypto: the item holding the key (default: {DEFAULT_CRYPTO_ITEM})",
    )
    fetch.add_argument(
        "--field",
        default=None,
        metavar="FIELD",
        help=f"--crypto: the field of that item (default: {DEFAULT_CRYPTO_FIELD})",
    )
    fetch.add_argument(
        "--secrets",
        nargs="?",
        const=DEFAULT_SECRETS_VAULT,
        default=None,
        metavar="1p:VAULT",
        help=f"fetch every item of this vault (alone: {DEFAULT_SECRETS_VAULT}) as "
        f"<ITEM>__<FIELD> variables, plus {secrets.SYSTEMS_ENV}, the prefixes "
        "set; an item titled _* is skipped",
    )
    fetch.add_argument(
        "--pypi-twine",
        nargs="?",
        const=DEFAULT_CRYPTO_VAULT,
        default=None,
        metavar="1p:VAULT",
        help=f"fetch {' and '.join(f for f, _ in TWINE_FIELDS)} from item "
        f"{TWINE_ITEM} of this vault (alone: {DEFAULT_CRYPTO_VAULT}) as "
        f"{' and '.join(n for _, n in TWINE_FIELDS)}, the names twine reads",
    )
    _common(
        fetch,
        {
            FMT_EXPORT: "export lines for a shell to eval",
            "view": "the names fetched, never the values",
            "json": "JSON Lines, the values included",
        },
        FMT_EXPORT,
    )
    push = sub.add_parser(
        PUSH,
        help="pushes a 1Password item to a vault, replacing what is filed under its title",
        description=(
            "Pushes one 1Password item to a vault, replacing what is filed under "
            "its title: delete, then create, since 1Password keys an item on the id "
            "it assigns and a create alone would make a second one. The item goes "
            "to `op` on stdin, never in argv or a file. `tdd system 1p-template` "
            "and `tdd system info --format 1p` write one; so does `op item get "
            "--format=json`, whose identity (id, vault, timestamps, field "
            "references) is dropped on the way."
        ),
    )
    push.add_argument(
        "--vault",
        required=True,
        metavar="1p:VAULT",
        help="the vault to push the item to, as a provider ref",
    )
    push.add_argument(
        "--entry",
        required=True,
        metavar="PATH",
        help="the item JSON (`-` reads it from stdin)",
    )
    _common(push, {"view": "one line", "json": "JSON Lines"}, "view")


def main() -> int:
    return cli.run(
        NAME,
        DESCRIPTION,
        body,
        configure=configure,
        formats={FMT_EXPORT: "fetch's export lines, for a shell to eval"},
        default_format=FMT_EXPORT,
    )


if __name__ == "__main__":
    raise SystemExit(main())
