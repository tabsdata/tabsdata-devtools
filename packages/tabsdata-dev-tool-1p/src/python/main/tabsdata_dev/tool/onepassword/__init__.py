#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd _1p`` -- what tdd reads from and files in 1Password.

    tdd _1p fetch [--crypto 1p:VAULT [--item ITEM] [--field FIELD]]
                  [--secrets 1p:VAULT]
    tdd _1p set --vault 1p:VAULT --entry PATH|-

``--crypto`` reads the one field that is the descriptor key
(``_TDD_CRYPTO_KEY``) out of a personal vault; ``--secrets`` sweeps a shared
vault, every item's fields becoming ``<ITEM>__<FIELD>`` variables, plus
``_TDD_SYSTEMS``, the list of the prefixes it set. Both, one call: the result is
``export`` lines, printed as the outcome for the caller to apply.

This is plumbing for ``tdd env set --crypto/--secrets``. A Python process
cannot change the shell that runs it, so ``env`` -- a shell command -- runs this
and applies the lines, and nothing is written to disk. The providers live in
``common.core.secrets``; this tool only chooses what to read and checks it.

``set`` files one item in a vault, replacing what is filed under its title
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
    "1Password for tdd: fetch the crypto key and secrets as export lines "
    "(tdd env), file an item in a vault"
)

FETCH = "fetch"
SET = "set"
ACTIONS = (FETCH, SET)
# Where the descriptor key sits in a personal vault, unless told otherwise.
# The vault itself has no default here: `tdd env` passes the one it keeps in
# env.toml, and a direct caller names it.
DEFAULT_CRYPTO_ITEM = "DevSecrets"
DEFAULT_CRYPTO_FIELD = "TD_BACKENDS_CRYPTO_KEY"


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


def _set(args: argparse.Namespace, out: render.Renderer) -> int:
    vault = _vault("--vault", args.vault)  # refused before the entry is read
    item = read_entry(args.entry)
    title = str(item["title"])
    out.info(f"filing '{title}' in {args.vault}")
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


def body(args: argparse.Namespace, out: render.Renderer) -> int:
    if args.action not in ACTIONS:
        raise ToolError(f"a subcommand is required: {', '.join(ACTIONS)} (see --help)")
    if args.action == SET:
        return _set(args, out)
    if not args.crypto and not args.secrets:
        raise ToolError(
            "nothing to fetch: pass --crypto 1p:VAULT and/or --secrets 1p:VAULT"
        )
    if (args.item or args.field) and not args.crypto:
        raise ToolError("--item and --field say where the crypto key is; pass --crypto")
    if args.secrets:
        _ref("--secrets", args.secrets)  # refused before anything is read
    found: dict[str, str] = {}
    if args.crypto:
        item = args.item or DEFAULT_CRYPTO_ITEM
        field = args.field or DEFAULT_CRYPTO_FIELD
        out.debug(f"reading {args.crypto}/{item}/{field}")
        found[secrets.CRYPTO_KEY_ENV] = crypto_key(args.crypto, item, field)
    if args.secrets:
        out.debug(f"reading every item of {args.secrets}")
        found.update(secrets.with_systems_var(secrets.fetch(args.secrets)))
    # The outcome IS the lines to apply: `tdd env` evaluates what comes out.
    return out.ok(secrets.render(found, "export"), names=list(found))


def _common(sub: argparse.ArgumentParser) -> None:
    """--format/--verbose after the subcommand word too."""
    sub.add_argument(
        "--format",
        choices=("json", "view"),
        default=argparse.SUPPRESS,
        help="json is JSON Lines, one event per line (default: view)",
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
        f"examples: tdd {NAME} {FETCH} --crypto 1p:Employee --secrets 1p:dev_xp\n"
        f"          tdd system 1p-template --type s3 | tdd {NAME} {SET} "
        "--vault 1p:dev_xp --entry -"
    )
    sub = p.add_subparsers(dest="action", metavar="SUBCOMMAND")
    fetch = sub.add_parser(
        FETCH,
        help="print the crypto key and/or a vault's secrets as export lines",
        description=(
            "Read the descriptor crypto key (--crypto) and/or every secret of a "
            "shared vault (--secrets) from 1Password and print them as export "
            "lines, the outcome of the command, for a shell to apply -- `tdd env "
            "set --crypto --secrets` does. The values are in the output: that is "
            "what it is for."
        ),
    )
    fetch.add_argument(
        "--crypto",
        default=None,
        metavar="1p:VAULT",
        help=f"read {secrets.CRYPTO_KEY_ENV} from this vault; at least "
        f"{secrets.CRYPTO_KEY_MIN_LEN} characters",
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
        default=None,
        metavar="1p:VAULT",
        help="read every item of this vault as <ITEM>__<FIELD> variables, plus "
        f"{secrets.SYSTEMS_ENV}, the prefixes set; an item titled _* is skipped",
    )
    _common(fetch)
    put = sub.add_parser(
        SET,
        help="file a 1Password item in a vault, replacing what is filed under its title",
        description=(
            "Put one 1Password item in a vault, replacing what is filed under its "
            "title: delete, then create, since 1Password keys an item on the id it "
            "assigns and a create alone would make a second one. The item goes to "
            "`op` on stdin, never in argv or a file. `tdd system 1p-template` and "
            "`tdd system info --format 1p` write one; so does `op item get "
            "--format=json`, whose identity (id, vault, timestamps, field "
            "references) is dropped on the way."
        ),
    )
    put.add_argument(
        "--vault",
        required=True,
        metavar="1p:VAULT",
        help="the vault to file the item in, as a provider ref",
    )
    put.add_argument(
        "--entry",
        required=True,
        metavar="PATH",
        help="the item JSON (`-` reads it from stdin)",
    )
    _common(put)


def main() -> int:
    return cli.run(NAME, DESCRIPTION, body, configure=configure)


if __name__ == "__main__":
    raise SystemExit(main())
