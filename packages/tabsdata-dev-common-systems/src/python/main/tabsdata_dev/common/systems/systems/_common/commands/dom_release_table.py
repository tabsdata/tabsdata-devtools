#
# Copyright 2026 Tabsdata Inc.
#

"""Undo capture-table: stop capturing a table of the domain, remove its
registration and CD table, and drop the table itself with ``--drop``.

Best-effort, like the backend's deregistration: a test cleaning up must not fail
because part of the registration was never made, so releasing a table that was
never captured succeeds.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, constants, descriptor


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser, multi=False)
    cli.add_domain_dir(parser)
    parser.add_argument(
        constants.OPT_TABLE,
        required=True,
        metavar="NAME",
        help="the captured table, in the domain's schema, to release",
    )
    parser.add_argument(
        constants.OPT_DROP,
        action="store_true",
        help="drop the table too once it is released",
    )


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo)
    a = ctx.args
    ctx.system.deregister_table(ctx.info.meta, a.table, drop=a.drop)
    console.result({"table": a.table.upper(), "dropped": a.drop})
    console.good(f"released {a.table.upper()} of domain '{ctx.name}'")
    return 0
