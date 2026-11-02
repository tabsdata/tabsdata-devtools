#
# Copyright 2026 Tabsdata Inc.
#

"""pgvector on the systems whose server has it installed: ``postgrespgvector``
(the container) and ``postgresnativepgvector`` (the native server).

Installed is all such a system promises, as a DBA who only installed the
package would: creating the extension is the product's job, and its tests'. A
domain is therefore created with pgvector off; ``domain create --pgvector on``
stands for the DBA who also created it, running ``CREATE EXTENSION vector`` in
the domain's database (as the superuser: pgvector is not a trusted extension)
and recording ``PGVECTOR`` in the domain's meta, which ``manifest`` replays.
Both types bind this module as their ``domain create``.
"""

from __future__ import annotations

import argparse
from dataclasses import replace

from tabsdata_dev.common.systems import cli
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.commands import dom_create
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import Admin

#: The domain meta key saying whether its database has the extension created.
PGVECTOR_KEY = "PGVECTOR"
PGVECTOR_ON = "on"
PGVECTOR_OFF = "off"

OPT_PGVECTOR = "--pgvector"


class PgvectorDomains:
    """The domain half of a pgvector system, mixed in ahead of its postgres
    backend, whose domain hooks it extends."""

    # What `domain create --pgvector` chose for the domain it is creating.
    _pgvector: str = PGVECTOR_OFF

    def use_pgvector(self, choice: str) -> None:
        """Bind ``--pgvector`` for the domain this create makes (on or off)."""
        if choice not in (PGVECTOR_ON, PGVECTOR_OFF):
            raise TdxError(
                f"--pgvector takes {PGVECTOR_ON} or {PGVECTOR_OFF}, not {choice!r}"
            )
        self._pgvector = choice

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        meta = super().domain_meta(sys_meta, entity_name, password)
        meta[PGVECTOR_KEY] = self._pgvector
        return meta

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        super().provision_domain(sys_meta, entity_name, domain_meta, force=force)
        if domain_meta.get(PGVECTOR_KEY) == PGVECTOR_ON:
            self._create_extension(self._admin(sys_meta), entity_name)

    def _create_extension(self, admin: Admin, db: str) -> None:
        print(f">>> pgvector: CREATE EXTENSION vector in '{db}'")
        self._run_admin(
            replace(admin, db=db), ["CREATE EXTENSION IF NOT EXISTS vector"]
        )


def add_arguments(parser: argparse.ArgumentParser) -> None:
    dom_create.add_arguments(parser)
    parser.add_argument(
        OPT_PGVECTOR,
        dest="pgvector",
        choices=(PGVECTOR_ON, PGVECTOR_OFF),
        default=PGVECTOR_OFF,
        help=f"create the pgvector extension in the domain's database "
        f"(default {PGVECTOR_OFF}: installed on the server, created nowhere)",
    )


def run(ctx: cli.Context) -> int:
    ctx.system.use_pgvector(ctx.args.pgvector)
    return dom_create.run(ctx)
