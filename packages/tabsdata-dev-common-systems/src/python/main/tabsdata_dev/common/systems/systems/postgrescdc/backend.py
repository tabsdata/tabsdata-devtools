#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL configured for change-data-capture (logical decoding via wal2json).

A variant of the plain ``postgres`` system — same image, domain model and DDL
(reused via ``ddl_from_slug``) — but the server runs with ``wal_level=logical``
(plus generous slot/sender limits), the ``wal2json`` output plugin is installed
at start (the base image doesn't ship it), each domain owner gets the
``REPLICATION`` attribute, and every model table is set ``REPLICA IDENTITY FULL``
so UPDATE/DELETE change records carry full before-images.

Each domain also owns a logical replication slot, created with its database and
named after it (``REPLICATION_SLOT`` in the domain's meta, ``${D0__REPLICATION_SLOT}``
to a function): the slot a stream publisher over the domain uses, with
``replication_slot_behavior="reuse"``. A slot name is unique across the whole server,
not per database, so a name a function chose itself would collide with every other run
against the same system. Destroying the domain ends whatever still reads the slot and
drops it before the database -- Postgres never drops a database a slot is on, and the
reader may well outlive its project. So does every other slot on the database, such as
one a stream created for itself (``replication_slot_behavior="create"``): a logical slot
belongs to one database and nothing else can read it, so it goes with the domain.
"""

from __future__ import annotations

import hashlib
import re
import time
from dataclasses import replace
from typing import ClassVar

from tabsdata_dev.common.systems import datagen
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.shell import docker_exec
from tabsdata_dev.common.systems.sql_runner import run_sql_text
from tabsdata_dev.common.systems.systems._common import container_info
from tabsdata_dev.common.systems.systems._common.sql import Admin
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

#: The domain meta key holding the domain's own replication slot.
REPLICATION_SLOT_KEY = "REPLICATION_SLOT"
_SLOT_MAX = 63  # NAMEDATALEN - 1
_SLOT_UNSAFE = re.compile(r"[^a-z0-9_]")
#: How often a drop is retried when the reader reconnects between the
#: terminate and the drop, and how long to wait between tries.
_DROP_TRIES = 5
_DROP_PAUSE = 1.0


def replication_slot_of(database: str) -> str:
    """The slot a domain's database owns: its name lowercased, with anything a slot
    name may not hold made ``_`` -- slot names are lowercase letters, digits and
    ``_`` -- and, past 63 characters, cut and suffixed with a hash of the full name
    so two long names cannot meet."""
    name = _SLOT_UNSAFE.sub("_", database.lower())
    if len(name) <= _SLOT_MAX:
        return name
    digest = hashlib.sha256(database.encode()).hexdigest()[:12]
    return f"{name[: _SLOT_MAX - len(digest) - 1]}_{digest}"


class Postgrescdc(Postgres):
    slug = "postgrescdc"
    label = "PostgreSQL (CDC)"
    ddl_from_slug = "postgres"

    cmd_args: ClassVar[list[str]] = [
        *Postgres.cmd_args,
        "-c",
        "wal_level=logical",
        "-c",
        "max_replication_slots=1024",
        "-c",
        "max_wal_senders=1024",
        "-c",
        "wal_keep_size=1024",
        "-c",
        "max_logical_replication_workers=4",
    ]

    @staticmethod
    def _pg_major() -> str:
        return container_info.POSTGRES.version.split(".", 1)[0].split("-", 1)[0] or "17"

    def post_provision(self, container: str, password: str) -> None:
        super().post_provision(container, password)
        pkg = f"postgresql-{self._pg_major()}-wal2json"
        print(f">>> installing {pkg} (wal2json output plugin) for logical decoding …")
        cp = docker_exec(
            container,
            "bash",
            "-lc",
            f"apt-get update && apt-get install -y {pkg}",
            user="root",
        )
        if cp.returncode != 0:
            raise TdxError(
                f"could not install {pkg} (needed for Postgres CDC): "
                f"{cp.stderr.strip() or cp.stdout.strip()}"
            )
        self._allow_wal2json(container)

    def provision_domain(
        self,
        sys_meta: dict[str, str],
        entity_name: str,
        domain_meta: dict[str, str],
        *,
        force: bool = False,
    ) -> None:
        """A system created before :meth:`_allow_wal2json` existed is allowed
        here, before the domain's slot is created."""
        container = sys_meta.get("DOCKER_CONTAINER_NAME", "")
        if container:
            self._allow_wal2json(container)
        super().provision_domain(sys_meta, entity_name, domain_meta, force=force)

    def _psql(self, container: str, sql: str) -> str:
        cp = docker_exec(container, "psql", "-U", self.root_user, "-qAtX", "-c", sql)
        if cp.returncode != 0:
            raise TdxError(
                f"psql failed in {container}: {cp.stderr.strip() or cp.stdout.strip()}"
            )
        return cp.stdout.strip()

    def _allow_wal2json(self, container: str) -> None:
        """Let replication slots use wal2json.

        Since the August 2026 minor releases (18.6, 17.11, 16.15, 15.19, 14.24)
        a slot may only use the output plugins ``output_plugin_libraries``
        lists, by default only PostgreSQL's own (``pgoutput``,
        ``test_decoding``). An older server has no such setting and allows any
        installed plugin, so it is left alone."""
        present, value = self._psql(
            container,
            "select current_setting('output_plugin_libraries', true) is not null, "
            "coalesce(current_setting('output_plugin_libraries', true), '')",
        ).split("|", 1)
        if present != "t":
            return
        allowed = [name.strip().strip('"') for name in value.split(",") if name.strip()]
        if "wal2json" in allowed:
            return
        print(">>> allowing wal2json as a logical decoding output plugin …")
        # A list setting takes one quoted value per element: a single quoted
        # string would be one library named after the whole list.
        elements = ", ".join(f"'{name}'" for name in [*allowed, "wal2json"])
        self._psql(container, f"alter system set output_plugin_libraries = {elements}")
        self._psql(container, "select pg_reload_conf()")
        shown = self._psql(container, "show output_plugin_libraries")
        if "wal2json" not in [name.strip().strip('"') for name in shown.split(",")]:
            raise TdxError(
                f"wal2json is still not allowed as an output plugin in {container} "
                f"(output_plugin_libraries = {shown})"
            )

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        meta = super().domain_meta(sys_meta, entity_name, password)
        meta[REPLICATION_SLOT_KEY] = replication_slot_of(meta["DATABASE"])
        return meta

    def _do_create(self, admin: Admin, db: str, user: str, password: str) -> None:
        """The database, its owner and then its slot -- a logical slot belongs to
        one database and is created from a connection to it."""
        super()._do_create(admin, db, user, password)
        slot = replication_slot_of(db)
        print(f">>> CDC: replication slot '{slot}' (wal2json)")
        self._run_admin(
            replace(admin, db=db),
            [f"SELECT pg_create_logical_replication_slot('{slot}', 'wal2json')"],
        )

    def _do_delete(self, admin: Admin, name: str) -> None:
        """Every replication slot on the database, then the database. A logical
        slot belongs to one database and is of no use without it -- nothing
        else can read it -- so whoever made it, it goes with the domain: the
        domain's own, and those a stream created for itself
        (``replication_slot_behavior="create"``)."""
        for slot in self._query_admin(admin, _slots_on_sql(name)):
            self._drop_slot(admin, slot)
        super()._do_delete(admin, name)

    def _drop_slot(self, admin: Admin, slot: str) -> None:
        """End whatever reads `slot` and drop it. The reader -- a stream
        publisher whose project is gone -- may reconnect between the two, so a drop
        refused as active is tried again."""
        print(f">>> CDC: dropping replication slot '{slot}'")
        for attempt in range(1, _DROP_TRIES + 1):
            try:
                self._run_admin(
                    admin,
                    [
                        (
                            "SELECT pg_terminate_backend(active_pid) FROM pg_replication_slots "
                            f"WHERE slot_name = '{slot}' AND active_pid IS NOT NULL"
                        ),
                        f"SELECT pg_drop_replication_slot('{slot}')",
                    ],
                )
                return
            except TdxError:
                if attempt == _DROP_TRIES:
                    raise
                time.sleep(_DROP_PAUSE)

    def create_domain_sql(self, db: str, user: str, password: str) -> list[str]:
        # The owner role needs REPLICATION to open a logical-replication connection.
        return super().create_domain_sql(db, user, password) + [
            f'ALTER ROLE "{user}" WITH REPLICATION'
        ]

    def after_install_schema(self, meta: dict[str, str], model: str) -> None:
        tables = datagen.entities_of(model)
        if not tables:
            return
        print(f">>> CDC: REPLICA IDENTITY FULL on {len(tables)} table(s)")
        with self.data_plane_uri(meta) as uri:
            run_sql_text(
                uri,
                "\n".join(f'ALTER TABLE "{t}" REPLICA IDENTITY FULL;' for t in tables),
            )


def _slots_on_sql(database: str) -> str:
    """The replication slots on `database`."""
    return (
        "SELECT slot_name FROM pg_replication_slots "
        f"WHERE database = '{database}' ORDER BY slot_name"
    )
