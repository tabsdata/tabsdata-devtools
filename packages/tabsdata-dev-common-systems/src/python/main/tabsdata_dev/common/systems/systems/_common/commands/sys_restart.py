#
# Copyright 2026 Tabsdata Inc.
#

"""Restart a system tdd runs (e.g. after a host or Docker restart).

A container is restarted; a native server is restarted when it runs and started
when the machine's restart left it stopped."""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, ssh


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_sys(parser)
    cli.add_sys_dir(parser)
    cli.add_latch(parser)
    cli.add_manifest(parser, "restart")


def run(ctx: cli.Context) -> int:
    assert ctx.info is not None
    if ssh.is_tunnelled(ctx.info.meta):
        # The container is the far host's to restart; all this end owns is the
        # tunnel, and bouncing that would not restart anything.
        console.warn(f"'{ctx.name}' is reached over an ssh tunnel — nothing to restart")
        return 0
    done = ctx.system.restart_system(ctx.info.meta)
    console.good(f"{done or 'restarted'} system '{ctx.name}'")
    return 0
