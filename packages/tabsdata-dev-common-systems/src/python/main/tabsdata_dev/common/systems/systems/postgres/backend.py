#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL backend -- the dialect (:class:`PostgresDialect`) in a docker-run
container.

A container has one address and records it under both of the family's network
names (``INTERNAL_HOST`` and ``EXTERNAL_HOST``); the server's version is asked
once the container answers.
"""

from __future__ import annotations

from typing import ClassVar

from tabsdata_dev.common.systems.systems._common.hosting.container import images
from tabsdata_dev.common.systems.systems._common.hosting.container.single import (
    SingleContainerHosting,
)
from tabsdata_dev.common.systems.systems.postgres.dialect import PostgresDialect

#: The server settings every postgres tdd runs boots with, in a container
#: (``-c`` flags) or natively (its configuration file).
#: Both knobs match what td-database's own embedded server boots with. The
#: Rust db tests run 32-way parallel, each holding an admin, a serving and a
#: teardown pool, which overruns the image default of 100 connections; and
#: each builds a whole schema in one transaction, holding a lock per object
#: until it commits, which the default lock-table sizing (64 per transaction)
#: cannot seat concurrently -- it fails as "out of shared memory" (53200).
SERVER_SETTINGS: dict[str, str] = {
    "max_connections": "500",
    "max_locks_per_transaction": "1024",
}


class Postgres(SingleContainerHosting, PostgresDialect):
    slug = "postgres"
    label = "PostgreSQL"

    image = images.POSTGRES.ref
    image_platform = images.POSTGRES.platform
    internal_port = 5432

    cmd_args: ClassVar[list[str]] = [
        arg
        for key, value in SERVER_SETTINGS.items()
        for arg in ("-c", f"{key}={value}")
    ]

    def provider_meta(self, sys_meta: dict[str, str]) -> dict[str, str]:
        return {
            "IMAGE": sys_meta.get("IMAGE", ""),
            "SYS_DOCKER_CONTAINER_NAME": sys_meta.get("DOCKER_CONTAINER_NAME", ""),
            "SYS_DOCKER_CONTAINER_ID": sys_meta.get("DOCKER_CONTAINER_ID", ""),
        }

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        # One address, recorded under both names: a container is reached at the
        # host it advertises whichever side of it you are on.
        host = self.hostname
        meta = {
            "INTERNAL_HOST": host,
            "EXTERNAL_HOST": host,
            "PORT": o.get("PORT") or str(self.next_free_port()),
            "DATABASE": self.admin_db,
            "USER": self.root_user,
            "PASSWORD": o.get("PASSWORD") or self.generate_password(),
            "VERSION": "",  # filled in by the probe once the server is up
            "DOCKER_CONTAINER_NAME": self.container_name(name),
            "IMAGE": self.image,
        }
        self._plane_keys(meta, self.admin_db, meta["USER"], meta["PASSWORD"])
        return meta

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        extra = super().provision_system(meta, force=force)
        # The container answers now, so ask it what it is. Both go back as the
        # `extra` a create writes to the descriptor on its second pass.
        return {**extra, "VERSION": self._probe_version({**meta, **extra})}

    def env_vars(self, password: str) -> dict[str, str]:
        return {"POSTGRES_PASSWORD": password}

    def ready_exec_cmd(self, password: str) -> list[str]:
        return ["pg_isready", "-U", self.root_user, "-h", "localhost", "-q"]
