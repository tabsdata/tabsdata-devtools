#
# Copyright 2026 Tabsdata Inc.
#

"""Remove the domain's model: its entities and every row in them.

The inverse of ``create-model``: the domain stays (``destroy`` removes that),
empty, with no model recorded, so ``create-model`` may install this or another
model next without ``--force``. What "removing a schema" means is the backend's
(``uninstall_schema``): tables dropped, staged files or topics deleted, CDC
registrations withdrawn first, a record-only model simply forgotten.
"""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, datagen, descriptor
from tabsdata_dev.common.systems.errors import TdxError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)
    cli.add_latch(parser)


def run(ctx: cli.Context) -> int:
    assert isinstance(ctx.info, descriptor.DomainInfo) and ctx.path is not None
    info = ctx.info
    model = info.model
    if not model:
        raise TdxError(f"domain '{ctx.name}' has no model — nothing to delete")
    before = dict(info.entities)
    ctx.system.uninstall_schema(info.meta, model)
    descriptor.clear_model(ctx.path)
    if console.json_mode():
        console.result({name: datagen.iud(delete=n) for name, n in before.items()})
    else:
        console.good(f"removed model '{model}' from domain '{ctx.name}'")
    return 0
