#
# Copyright 2026 Tabsdata Inc.
#

"""List the models available for a domain's system (those with DDL present)."""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import cli, console, datagen


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_domain(parser)
    cli.add_domain_dir(parser)


def run(ctx: cli.Context) -> int:
    avail = ctx.system.available_models()
    if not avail:
        console.out("(no models available for this system)")
        return 0
    console.out(
        "Available models  "
        "(* grows with create-data --size;  (I/U/D) = modify-data ops;  "
        "(fixed) = not changed by modify-data;  (sentinel) = sentinel-data only)"
    )
    for model in avail:
        sizeable = set(datagen.sizeable_entities(model))
        # The verbs each entity takes on this system: a file domain inserts
        # (and changes a snapshot), a topic only appends.
        ops_by = {
            e.table: datagen.verbs_on(ctx.system, e)
            for e in datagen.load_model(model).entities
        }
        names = datagen.entities_of(model)
        width = max((len(n) for n in names), default=0)
        console.out(f"  {model}")
        for name in names:
            star = "*" if name in sizeable else " "
            if ops_by.get(name):
                tag = f"({datagen.ops_tag(ops_by[name])})"
            elif name == datagen.SENTINEL_ENTITY:
                tag = "(sentinel)"
            else:
                tag = "(fixed)"
            console.out(f"    {name:<{width}} {star} {tag}")
    return 0
