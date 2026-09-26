#
# Copyright 2026 Tabsdata Inc.
#

"""Delete the domain's data, keeping its model installed and empty.

The model's schema is dropped and installed again rather than each entity being
emptied in place: that is the reload ``create-data --force`` already does, so a
backend whose "empty" is not a ``DELETE`` (a file domain's staged shards, a
kafka domain's topics, a CDC domain's capture registrations) gets it right for
free. The domain is left as ``create-model`` leaves it -- every entity at zero
rows, the ``modify-data`` seed reset -- so ``create-data`` runs next without
``--force``. A domain with no data is emptied all the same: a loop that deletes
on every pass need not know whether the last pass loaded any.
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
    ctx.system.install_schema(info.meta, model, force=True)
    entity_names = datagen.entities_of(model)
    descriptor.set_model(ctx.path, model, entity_names)
    if console.json_mode():
        console.result({name: datagen.iud(delete=n) for name, n in before.items()})
    else:
        console.good(
            f"deleted {sum(before.values())} row(s) from domain '{ctx.name}' "
            f"(model '{model}' kept)"
        )
    return 0
