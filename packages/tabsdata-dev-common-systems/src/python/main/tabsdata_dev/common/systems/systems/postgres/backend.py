#
# Copyright 2026 Tabsdata Inc.
#

"""PostgreSQL backend — a docker-run container, and the shape all five share.

A domain is a database with a dedicated owner role of the same name. Admin runs
as the ``postgres`` superuser against the ``postgres`` maintenance database;
``CREATE`` / ``DROP DATABASE`` can't run inside a transaction, so admin SQL is
executed in autocommit.

**The info block.** ``postgres``, ``postgrescdc``, ``awspostgres``,
``gcppostgres`` and ``azpostgres`` are one class chain (``ManagedPostgres``
extends this), so the vocabulary a descriptor speaks is defined once, here, and
every one of the five reads alike::

    INTERNAL_HOST  EXTERNAL_HOST  PORT  DATABASE  USER  PASSWORD  VERSION
    INTERNAL_SQLALCHEMY_URI  EXTERNAL_SQLALCHEMY_URI
    INTERNAL_URI             EXTERNAL_URI

on top of which each adds only what its provider has: the docker keys here, the
``AWS_*`` / ``GCP_*`` / ``AZ_*`` groups and the TLS pair on the managed three.

**Two networks, always named.** A managed instance answers on a public address
and on a private one inside its VPC, and which is usable is a property of the
reader rather than of the instance -- tdx runs on a laptop and reaches it at
``EXTERNAL_HOST``, a workload in the cluster has no route to that and reaches it
at ``INTERNAL_HOST``. A container has one address and records it under both
names: the split costs it nothing and buys every reader of any of the five one
set of keys to look for. ``URI`` is the credentials-free twin of
``SQLALCHEMY_URI`` for each plane -- what a connector under test is handed
beside its own ``USER`` / ``PASSWORD``.

Everything tdx does itself -- the probe, ``status``, the domain DDL, loading a
model's data -- goes over the external plane, since that is where tdx is.
"""

from __future__ import annotations

from contextlib import contextmanager
from dataclasses import replace
from urllib.parse import quote

from tabsdata_dev.common.systems.systems._common import container_info
from tabsdata_dev.common.systems.systems._common.host import DEFAULT_HOSTNAME
from tabsdata_dev.common.systems.systems._common.sql import Admin, SqlContainerBackend


class Postgres(SqlContainerBackend):
    slug = "postgres"
    label = "PostgreSQL"
    domain_word = "database"
    entity_aliases = ("SCHEMA",)  # fixtures also expose the domain db as `schema`
    max_entity_name_length = 63  # NAMEDATALEN - 1
    login_maxlen = 63  # the owner role is named after the database

    image = container_info.POSTGRES.ref
    image_platform = container_info.POSTGRES.platform
    internal_port = 5432
    root_user = "postgres"
    driver = "postgresql+psycopg2"
    admin_db = "postgres"
    admin_autocommit = True
    system_schemas = frozenset({"postgres", "template0", "template1"})

    # The family names its networks and spells "database" out, so the shared
    # code in _common/sql.py reads a domain's address and database from these.
    domain_host_key = "EXTERNAL_HOST"
    domain_db_key = "DATABASE"

    # Both knobs match what td-database's own embedded server boots with. The
    # Rust db tests run 32-way parallel, each holding an admin, a serving and a
    # teardown pool, which overruns the image default of 100 connections; and
    # each builds a whole schema in one transaction, holding a lock per object
    # until it commits, which the default lock-table sizing (64 per transaction)
    # cannot seat concurrently -- it fails as "out of shared memory" (53200).
    cmd_args = [
        "-c",
        "max_connections=500",
        "-c",
        "max_locks_per_transaction=1024",
    ]

    # ---- the shared info block (all five) --------------------------------

    def sqlalchemy_url(
        self, host: str, port: str, db: str = "", user: str = "", password: str = ""
    ) -> str:
        # The credentials are percent-encoded because SQLAlchemy decodes what it
        # parses out of a URL: a password may contain a literal '%NN', which would
        # otherwise arrive at the server as the single byte it escapes. quote()
        # (not quote_plus) — a space must be '%20', since SQLAlchemy unquotes with
        # unquote(). A generated password is drawn from the URL-unreserved set and
        # passes through untouched; one somebody supplied with --password need not.
        # TLS is added by the caller: it differs between an admin connection and a
        # recorded URI.
        creds = f"{quote(user, safe='')}:{quote(password, safe='')}@" if user else ""
        tail = f"/{db}" if db else ""
        return f"{self.driver}://{creds}{host}:{port}{tail}"

    def _plane_keys(
        self, meta: dict[str, str], db: str, user: str, password: str
    ) -> None:
        """Write both planes' URI pairs into `meta`, from the hosts and port it
        already carries. One helper for the container and managed halves, so the
        four keys cannot come out built two different ways."""
        port = meta.get("PORT", "")
        for plane in ("INTERNAL", "EXTERNAL"):
            host = meta.get(f"{plane}_HOST", "")
            if not host:
                # An instance with no address on that network reads as absent,
                # not as a `postgresql://:5432` somebody could try to connect to.
                meta[f"{plane}_SQLALCHEMY_URI"] = meta[f"{plane}_URI"] = ""
                continue
            meta[f"{plane}_SQLALCHEMY_URI"] = self.finish_uri(
                self.sqlalchemy_url(host, port, db=db, user=user, password=password),
                meta,
            )
            meta[f"{plane}_URI"] = self.finish_uri(
                self.sqlalchemy_url(host, port, db=db), meta
            )

    def finish_uri(self, url: str, meta: dict[str, str]) -> str:
        """A recorded URI, ready to hand out. A container's is already done; a
        managed instance appends the TLS mode (and never the root certificate --
        that rides on tdx's own admin connections only)."""
        return url

    @contextmanager
    def data_plane_uri(self, meta: dict[str, str]):
        """The external plane -- tdx runs the loader itself, from where tdx is.
        A container needs nothing set up; ManagedPostgres overrides to write the
        root certificate libpq wants as a path."""
        yield meta["EXTERNAL_SQLALCHEMY_URI"]

    def _probe_version(self, meta: dict[str, str]) -> str:
        """What the server says it is, asked once at create over the admin
        connection (so a managed instance's root certificate is in play). Recorded
        rather than derived: an image tag names what was pulled, not what is
        running, and a managed instance's version is the provider's to change.
        Frozen at create -- after an upgrade, `create --force` refreshes it."""
        rows = self._query_admin(self._admin(meta), "SHOW server_version")
        # A container answers "18.4"; a managed instance can answer
        # "16.3 (Ubuntu 16.3-1.pgdg22.04+1)". The number is the part they agree on.
        return rows[0].split()[0] if rows else ""

    def _admin(self, sys_meta: dict[str, str]) -> Admin:
        """The admin connection, over the plane tdx is on."""
        return Admin(
            host=sys_meta.get("EXTERNAL_HOST", DEFAULT_HOSTNAME),
            port=sys_meta.get("PORT", ""),
            user=sys_meta.get("USER", self.root_user),
            password=sys_meta.get("PASSWORD", ""),
            db=sys_meta.get("DATABASE", ""),
        )

    def _sys_admin_meta(self, domain_meta: dict[str, str]) -> dict[str, str]:
        """The system's admin connection, rebuilt from a domain descriptor: the
        master's credentials and the *maintenance* database, never the domain's
        own -- a database cannot be dropped from a session connected to it."""
        return {
            **domain_meta,
            "USER": domain_meta.get("SYS_ADMIN_USER", self.root_user),
            "PASSWORD": domain_meta.get("SYS_ADMIN_PASSWORD", ""),
            "DATABASE": domain_meta.get("SYS_DATABASE", ""),
        }

    def destroy_domain(self, domain_meta: dict[str, str]) -> None:
        self._do_delete(
            self._admin(self._sys_admin_meta(domain_meta)),
            domain_meta[self.domain_db_key],
        )

    def domain_meta(
        self, sys_meta: dict[str, str], entity_name: str, password: str
    ) -> dict[str, str]:
        """The system's info block with the domain's own database and owner in
        it, so a domain descriptor is enough on its own -- and for the managed
        three the reader handed one is usually not where tdx ran."""
        admin = self._admin(sys_meta)
        login = self._login(entity_name)
        meta = {
            "INTERNAL_HOST": sys_meta.get("INTERNAL_HOST", ""),
            "EXTERNAL_HOST": sys_meta.get("EXTERNAL_HOST", ""),
            "PORT": admin.port,
            "DATABASE": entity_name,
            "USER": login,
            "PASSWORD": password,
            "VERSION": sys_meta.get("VERSION", ""),
            "SYS_ADMIN_USER": admin.user,
            "SYS_ADMIN_PASSWORD": admin.password,
            "SYS_DATABASE": sys_meta.get("DATABASE", ""),
        }
        # The provider group first: it carries the TLS mode, and `finish_uri`
        # reads that mode off the meta it is given -- built the other way round,
        # every recorded URI would quietly claim the class default instead of
        # what this system was created with.
        meta.update(self.provider_meta(sys_meta))
        self._plane_keys(meta, entity_name, login, password)
        return meta

    def provider_meta(self, sys_meta: dict[str, str]) -> dict[str, str]:
        """The keys past the shared block that a domain inherits from its system
        -- the docker pair here, a provider's own group on the managed three.
        Recorded because they are not derivable from a host that may be a bare
        IP, and a domain command never loads the system descriptor."""
        return {
            "IMAGE": sys_meta.get("IMAGE", ""),
            "SYS_DOCKER_CONTAINER_NAME": sys_meta.get("DOCKER_CONTAINER_NAME", ""),
            "SYS_DOCKER_CONTAINER_ID": sys_meta.get("DOCKER_CONTAINER_ID", ""),
        }

    # ---- container half ---------------------------------------------------

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

    def create_domain_sql(self, db: str, user: str, password: str) -> list[str]:
        return [
            f'CREATE DATABASE "{db}"',
            f"CREATE USER \"{user}\" WITH PASSWORD '{password}'",
            f'ALTER DATABASE "{db}" OWNER TO "{user}"',
            f'GRANT ALL PRIVILEGES ON DATABASE "{db}" TO "{user}"',
        ]

    def own_public_schema_sql(self, user: str) -> list[str]:
        """Run inside the new database, once it exists: give its owner the
        schema its tables go in."""
        return [f'ALTER SCHEMA public OWNER TO "{user}"']

    def _do_create(self, admin: Admin, db: str, user: str, password: str) -> None:
        """Create the database and its owner, then hand that owner `public`.

        Creating a database owned by a role is NOT enough to let that role put a
        table in it. Since PostgreSQL 15, `public` is no longer writable by
        everyone: it belongs to `pg_database_owner`, whose one implicit member is
        whoever owns the database -- which is why a stock server, and Cloud SQL,
        appear to work without this. Azure Flexible Server ships a template where
        `public` belongs to `azure_pg_admin` instead and grants the rest of the
        world USAGE alone, so the domain's own role could read its database and
        not write to it: `create-model` was the first command to find out, with a
        bare `permission denied for schema public`.

        Taking ownership rather than granting CREATE says the same thing about
        every one of the five, on any server and whatever its template does: the
        database exists for this domain, so the domain owns what is in it. It
        needs its own connection -- to the new database rather than the
        maintenance one -- which is why it is here and not another line of
        `create_domain_sql`.
        """
        super()._do_create(admin, db, user, password)
        self._run_admin(replace(admin, db=db), self.own_public_schema_sql(user))

    def delete_domain_sql(self, name: str) -> list[str]:
        # WITH (FORCE) (PG 13+) drops even with a lingering client session.
        return [
            f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
            f'DROP USER IF EXISTS "{self._login(name)}"',
        ]

    def list_schemas_sql(self) -> str:
        return (
            "SELECT datname FROM pg_database "
            "WHERE datistemplate = false AND datname <> 'postgres' "
            "ORDER BY datname"
        )
