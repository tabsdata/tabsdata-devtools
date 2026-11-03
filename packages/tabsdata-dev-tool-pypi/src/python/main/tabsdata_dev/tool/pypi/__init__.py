#
# Copyright 2026 Tabsdata Inc.
#

"""``tdd pypi``: build and publish pypi.tabsdata.com, a static index on S3.

`raw-wheels/` is the source of truth; everything else is derived from it and can
be thrown away and rebuilt::

    raw-wheels/<VERSION>/       the wheels + a MANIFEST        gitignored, yours
         │ generate [--version V]   (every release, or V alone)
         ▼
    pypi-wheels/staging/        the local staging tree         committed, minus *.whl
         │ push --lane staging  -> s3://td-pypi-staging    [--at NAME: <base>/NAME/, yours]
         │ promote
         ▼
    pypi-wheels/prod/           the local prod tree            committed, minus *.whl
         │ push --lane prod     -> s3://td-pypi-prod    two gates: git pushed, raw archived
         ▼
    https://pypi.tabsdata.com/simple/

    raw-wheels/  ⇄  push/fetch --lane raw  ⇄  s3://td-raw-wheels   the archive

Every tree ends with a root `index.json`, written **last**, so its presence
means complete and its absence means whatever produced it did not finish;
`check` asks exactly that. Yanking is a file, not a command: each tree's
`yanked.yaml` is read by `generate` and `promote` and never written by anything.

All of it runs at the root of a clone of `pypi-repo` -- see `repo.py` for why,
and `config --show` for where that is set.
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from tabsdata_dev.common.core import cli
from tabsdata_dev.common.core.errors import ToolError
from tabsdata_dev.common.core.render import Renderer

# Modules, not the functions inside them: several share a name with their module
# (generate, promote, push, push_raw, aws_check), and binding the function here
# would shadow the submodule for anyone doing `from tabsdata_dev.tool.pypi import
# push`. Same reason gsx imports `args as args_mod`.
from . import aws_check as aws_check_mod
from . import cache as cache_mod
from . import check as check_mod
from . import config as config_mod
from . import delete as delete_mod
from . import fetch as fetch_mod
from . import generate as generate_mod
from . import promote as promote_mod
from . import push as push_mod
from . import push_raw as push_raw_mod
from . import repo
from . import serve as serve_mod
from .config import (
    DEFAULT_AT,
    DEFAULT_CONFIG,
    DEFAULT_PARALLEL,
    DEFAULT_RAW,
    DEFAULT_TREE,
    LANES,
    POLICY,
    RAW,
)
from .tree import lane_tree

SERVING = tuple(POLICY)  # staging, prod


def _common(sub: argparse.ArgumentParser) -> argparse.ArgumentParser:
    """The options every command has, repeated on each subcommand.

    argparse only accepts a top-level option before the subcommand word, and
    the guidelines say everything after the command word belongs to the command
    -- so `tdd pypi check --lane staging --local --format json` has to work.
    SUPPRESS so an unused one here does not overwrite what was given before the
    subcommand (the same shape gsx uses)."""
    sub.add_argument(
        repo.OPTION,
        metavar="URL",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
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
    return sub


def _parallel(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--parallel",
        type=int,
        default=DEFAULT_PARALLEL,
        help=f"concurrent transfers (default {DEFAULT_PARALLEL})",
    )


def configure(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        repo.OPTION,
        metavar="URL",
        # A value and not None: config.from_parser leaves out an option with no
        # default, and this is the one option that most wants to live in the
        # file. Blanking it there reads as unset -- the guard says so.
        default=repo.DEFAULT,
        help="the remote of the repo holding the pypi meta; every subcommand "
        f"runs at the root of a clone of it (default {repo.DEFAULT})",
    )
    p.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    p.add_argument("--raw", type=Path, default=DEFAULT_RAW, help="raw-wheels/")
    p.add_argument(
        "--tree", type=Path, default=DEFAULT_TREE, help="pypi-wheels/, holding <lane>/"
    )
    sub = p.add_subparsers(dest="cmd", required=True, metavar="SUBCOMMAND")

    g = sub.add_parser(
        "generate",
        help="raw-wheels/ -> pypi-wheels/staging/, from scratch (staging/yanked.yaml "
        "kept and applied); index.json last (no AWS)",
    )
    g.add_argument(
        "--version",
        help="raw-wheels/<VERSION> only: a tree holding that one release, built "
        "from scratch like the full one -- what a push then makes the lane, or "
        "with --at NAME a developer's index of it (default: every release)",
    )
    pr = sub.add_parser(
        "promote",
        help="pypi-wheels/staging/ -> pypi-wheels/prod/, locally, from scratch "
        "(prod/yanked.yaml kept and applied); index.json last (no AWS)",
    )
    ac = sub.add_parser(
        "aws-check",
        help="are these credentials able to provision and publish? live read "
        "probes plus simulated writes; changes nothing",
    )

    s_ = sub.add_parser("serve", help="http.server on a local tree (no AWS)")
    s_.add_argument(
        "--lane",
        choices=SERVING,
        default="staging",
        help="which tree (default staging)",
    )
    s_.add_argument("--port", type=int, default=8000, help="default 8000")
    s_.add_argument(
        "--at",
        metavar="NAME",
        default=DEFAULT_AT,
        help="also serve the tree at /NAME/ as namespace NAME serves it once "
        f"`push --at NAME` publishes it (default {DEFAULT_AT}: the tree alone)",
    )

    c = sub.add_parser("check", help="is the index there? (complete generate/push)")
    c.add_argument("--lane", required=True, choices=SERVING, help="which lane")
    cx = c.add_mutually_exclusive_group(required=True)
    cx.add_argument(
        "--local", action="store_true", help="pypi-wheels/<lane>/index.json"
    )
    cx.add_argument("--remote", action="store_true", help="the lane's bucket")

    cc = sub.add_parser(
        "cache-clean",
        help="invalidate everything the lane's CloudFront distribution has cached "
        "(/*); the bucket is untouched",
    )
    cc.add_argument("--lane", required=True, choices=SERVING, help="which lane")
    cc.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="do not ask before invalidating (prod requires it)",
    )

    d = sub.add_parser(
        "push",
        help="--lane raw: raw-wheels/ -> the archive; "
        "--lane staging|prod: pypi-wheels/<lane>/ -> that bucket, exactly",
    )
    d.add_argument(
        "--lane", required=True, choices=LANES, help="raw: the archive; else a bucket"
    )
    d.add_argument(
        "--at",
        metavar="NAME",
        default=DEFAULT_AT,
        help="serving lanes: push into namespace NAME, served at <domain>/NAME/ "
        "beside the lane's own index, with files of its own and nobody else's "
        f"objects touched -- a developer's index (default {DEFAULT_AT}: the lane's)",
    )
    d.add_argument("--version", help="--lane raw: this release only (default: all)")
    d.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="--lane raw: overwrite archived filenames whose bytes changed",
    )
    d.add_argument(
        "--sync",
        action="store_true",
        help="--lane raw: delete archived objects that are not in raw-wheels/",
    )
    d.add_argument(
        "--full",
        action="store_true",
        help="serving lanes: delete everything in the bucket first (index first), "
        "then upload the whole tree (index last); no per-object comparison",
    )
    d.add_argument(
        "--dry-run", action="store_true", help="print the plan, write nothing"
    )
    d.add_argument(
        "--yes",
        "-y",
        action="store_true",
        help="do not ask before writing (prod requires it)",
    )
    _parallel(d)

    rm = sub.add_parser(
        "delete",
        help="--lane staging: delete the lane's own tree, or with --at NAME that "
        "namespace, from the bucket and the edge; staging only",
    )
    rm.add_argument(
        "--lane",
        required=True,
        choices=("staging",),
        help="staging: the published index is never deleted",
    )
    rm.add_argument(
        "--at",
        metavar="NAME",
        default=DEFAULT_AT,
        help="the namespace `push --at NAME` made; the lane's own tree, its "
        f"namespaces kept, when {DEFAULT_AT} (default {DEFAULT_AT})",
    )
    rm.add_argument(
        "--dry-run", action="store_true", help="print the plan, delete nothing"
    )
    rm.add_argument(
        "--yes", "-y", action="store_true", help="do not ask before deleting"
    )
    _parallel(rm)

    f = sub.add_parser(
        "fetch",
        help="--lane raw: the archive -> raw-wheels/; "
        "--lane staging|prod: that bucket -> pypi-wheels/<lane>/",
    )
    f.add_argument(
        "--lane", required=True, choices=LANES, help="raw: the archive; else a bucket"
    )
    f.add_argument("--version", help="--lane raw: this release only (default: all)")
    f.add_argument(
        "--force",
        "-f",
        action="store_true",
        help="re-download even what already matches",
    )
    f.add_argument(
        "--sync",
        action="store_true",
        help="delete local files the lane does not hold; asks first unless --yes",
    )
    f.add_argument(
        "--yes", "-y", action="store_true", help="do not ask before deleting"
    )
    _parallel(f)

    # Every subcommand also takes the common options, so they work on either
    # side of the subcommand word (see _common).
    for spec in (g, pr, ac, s_, c, cc, d, rm, f):
        _common(spec)

    p.epilog = "example: tdd pypi push --lane staging --dry-run"


def body(args: argparse.Namespace, out: Renderer) -> int:
    # The guard first, before any path is resolved: --raw and --tree are
    # relative, so anywhere but the root they name the wrong directory.
    repo.require_root(getattr(args, "pypi_repo", None))

    # Local-only commands do not read lanes.yaml, so they work before any AWS
    # resource or config exists.
    if args.cmd == "generate":
        return generate_mod.generate(
            args.raw, lane_tree(args.tree, "staging"), out, version=args.version
        )
    if args.cmd == "promote":
        return promote_mod.promote(
            lane_tree(args.tree, "staging"), lane_tree(args.tree, "prod"), out
        )
    if args.cmd == "serve":
        return serve_mod.serve(
            lane_tree(args.tree, args.lane),
            args.port,
            config_mod.check_at(args.at),
            out,
        )
    if args.cmd == "check" and args.local:
        return check_mod.check_local(lane_tree(args.tree, args.lane), out)

    cfg = config_mod.load(args.config)

    if args.cmd == "aws-check":
        return aws_check_mod.aws_check(cfg, out)
    if args.cmd == "check":
        return check_mod.check_remote(cfg, cfg.lane(args.lane), out)
    if args.cmd == "cache-clean":
        return cache_mod.cache_clean(cfg.lane(args.lane), out, assume_yes=args.yes)
    if args.cmd == "push":
        if args.lane == RAW:
            if args.full:
                raise ToolError("--full does not apply to the raw lane")
            if args.at != DEFAULT_AT:
                raise ToolError("--at applies to the serving lanes only")
            return push_raw_mod.push_raw(
                args.raw,
                cfg,
                version=args.version,
                dry_run=args.dry_run,
                assume_yes=args.yes,
                force=args.force,
                sync=args.sync,
                parallel=args.parallel,
                out=out,
            )
        for flag in ("version", "force", "sync"):
            if getattr(args, flag):
                raise ToolError(
                    f"--{flag} applies to --lane raw only; a serving lane always "
                    "becomes exactly the local tree (generate --version builds a "
                    "one-release tree)"
                )
        # assume_yes is never inferred from a non-tty: that would let a CI run
        # satisfy the prod lane's require_yes without anyone typing --yes.
        return push_mod.push(
            args.tree,
            cfg,
            cfg.lane(args.lane).with_at(args.at),
            dry_run=args.dry_run,
            assume_yes=args.yes,
            full=args.full,
            parallel=args.parallel,
            out=out,
        )
    if args.cmd == "delete":
        return delete_mod.delete(
            cfg,
            cfg.lane(args.lane).with_at(args.at),
            dry_run=args.dry_run,
            assume_yes=args.yes,
            parallel=args.parallel,
            out=out,
        )
    if args.cmd == "fetch":
        if args.lane == RAW:
            return fetch_mod.fetch_raw(
                args.raw,
                cfg,
                version=args.version,
                force=args.force,
                sync=args.sync,
                assume_yes=args.yes,
                parallel=args.parallel,
                out=out,
            )
        if args.version:
            raise ToolError("--version applies to --lane raw only")
        return fetch_mod.fetch_lane(
            args.tree,
            cfg,
            cfg.lane(args.lane),
            force=args.force,
            sync=args.sync,
            assume_yes=args.yes,
            parallel=args.parallel,
            out=out,
        )
    raise ToolError(f"unknown subcommand {args.cmd!r}")


DESCRIPTION = "build and publish pypi.tabsdata.com, a static index on S3"


def build_parser() -> argparse.ArgumentParser:
    """The full parser, common options included. The entry point does not need
    it -- cli.run() builds its own -- but a test that wants to check what an
    argument list parses to does."""
    p = cli.parser("pypi", DESCRIPTION)
    configure(p)
    return p


def main(argv: list[str] | None = None) -> int:
    os.environ.setdefault("AWS_RETRY_MODE", "standard")
    return cli.run(
        "pypi",
        DESCRIPTION,
        body,
        argv=argv,
        configure=configure,
    )
