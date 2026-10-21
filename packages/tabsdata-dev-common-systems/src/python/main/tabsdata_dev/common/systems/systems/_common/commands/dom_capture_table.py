#
# Copyright 2026 Tabsdata Inc.
#

"""Register a table of the domain for change capture, creating it first from
``--ddl`` when one is given, and report the CD table capture writes it into.

For a test that needs a CDC source table of its own: registration stays the
backend's (the same sequence ``create-model`` runs for the model's tables), so
the test does not reimplement it. ``release-table`` undoes it.
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
        help="the table, in the domain's schema, to capture",
    )
    parser.add_argument(
        constants.OPT_DDL,
        default=None,
        metavar="SQL",
        help="create the table with this statement before capturing it",
    )


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo)
    a = ctx.args
    cd_table = ctx.system.register_table(ctx.info.meta, a.table, ddl=a.ddl)
    console.result({"table": a.table.upper(), "cd_table": cd_table})
    console.good(f"capturing {a.table.upper()} of domain '{ctx.name}' into {cd_table}")
    return 0
