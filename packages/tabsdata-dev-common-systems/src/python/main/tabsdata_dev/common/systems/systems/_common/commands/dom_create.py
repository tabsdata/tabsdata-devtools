#
# Copyright 2026 Tabsdata Inc.
#

"""Create a domain (an entity-container + owner) in a system."""

from __future__ import annotations

import argparse

from tabsdata_dev.common.systems import (
    cli,
    console,
    constants,
    descriptor,
    naming,
    store,
)
from tabsdata_dev.common.systems.errors import TdxError


def add_arguments(parser: argparse.ArgumentParser) -> None:
    cli.add_sys(parser)
    cli.add_domain(parser, required=False, multi=False)
    cli.add_domain_prefix(parser)
    cli.add_sys_dir(parser)
    cli.add_domain_dir(parser)
    cli.add_force(parser)
    cli.add_dry_run(parser)
    cli.add_latch(parser)
    cli.add_manifest(parser, "create")
    cli.add_sync(parser)
    parser.add_argument(
        constants.OPT_NAME_IN_SYSTEM,
        default=None,
        metavar="NAME",
        help="name the entity-container verbatim (no d_<user>_<build>_ prefix)",
    )


def run(ctx: cli.Context) -> int:
    assert ctx.info is not None  # the system info (domain does not exist yet)
    a = ctx.args
    sys_meta = ctx.info.meta
    sys_name = a.sys
    domain = cli.apply_prefix(a.domain or sys_name, a.name_prefix)
    descriptor.validate_name(domain)
    dpath = store.domain_path(domain, a.domain_dir)
    if descriptor.is_descriptor(dpath) and not a.force:
        raise TdxError(f"domain '{domain}' already exists (use {constants.OPT_FORCE})")

    sysobj = ctx.system
    if a.dry_run:
        console.out(f"would create domain '{domain}' in system '{sys_name}'")
        return 0
    console.out(f"▶ creating domain '{domain}' in system '{sys_name}' …")
    if a.name_in_system:
        entity = a.name_in_system
        # Named verbatim by its caller, so nothing here picks a free one: one
        # already in the system belongs to someone else -- another run that
        # drew the same name, or one left behind -- and provisioning over it
        # would mix the two. Said before anything is written.
        taken = {e.lower() for e in sysobj.list_domain_entities(sys_meta)}
        if entity.lower() in taken and not a.force:
            raise TdxError(
                f"'{entity}' already exists in system '{sys_name}' -- another "
                f"run's, or one left behind (tdd system purge --sys {sys_name} "
                f"--external-prefix {entity} --force drops it)"
            )
    else:
        existing = set(sysobj.list_domain_entities(sys_meta))
        entity = naming.fit_entity_name(
            naming.external_name(domain), sysobj.max_entity_name_length, existing
        )
    password = sysobj.new_domain_password()
    dmeta = sysobj.domain_meta(sys_meta, entity, password)
    dmeta["SYSTEM_KIND"] = sysobj.kind
    # entity-term key(s) = the external name, named for the system's vocabulary
    # (DATABASE / SCHEMA / FOLDER / PREFIX / DATASET / …).
    dmeta[sysobj.domain_word.upper()] = entity
    for alias in getattr(sysobj, "entity_aliases", ()):
        dmeta[alias] = entity
    # Persist before provisioning (its baked SYS_* back-refs let destroy tear a
    # partial create down from disk).
    descriptor.write_domain(
        dpath,
        sysobj.slug,
        domain,
        sys_name=sys_name,
        sys_uuid=ctx.info.uuid,
        external_name=entity,
        meta=dmeta,
    )
    sysobj.provision_domain(sys_meta, entity, dmeta, force=a.force)
    console.good(f"created domain '{domain}' -> {entity} in system '{sys_name}'")
    return 0
