#
# Copyright 2026 Tabsdata Inc.
#

"""``ManagedPostgres`` — the shape a provider-managed PostgreSQL instance shares.

AWS RDS and GCP Cloud SQL differ in almost nothing tdx cares about: both are
externally owned (there is nothing to run, so ``create`` reads the connection
from the environment and probes it), and in both the master user is *not* a
superuser, which is what shapes the domain DDL.

A domain is still a DATABASE owned by a dedicated role, but a non-superuser
master can only create a database owned by a role it is a member of, so the owner
role is created and granted to the master *before* the database. The owner also
gets ``CREATEROLE`` so a test can add roles of its own and grant them privileges
on its database. Those roles are the owner's to drop: it is the recorded grantor
of the memberships it handed out, so (PostgreSQL 16+) it cannot be dropped while
they exist -- deleting a domain drops the roles the owner administers between the
database and the owner. A purge that died between those drops used to leave the
owner behind with no database, invisible to a listing of ``pg_database``; owner
roles the master is a member of are listed as domain entities too, so such a
remnant is purged (and never collided with by a create) like any other domain.

That last query is why :attr:`role_prefixes` exists. A managed instance grants
its master service roles of its own -- ``rds_*`` on RDS, ``cloudsql*`` on Cloud
SQL -- which are memberships, not domains. A subclass that forgets its provider's
prefix does not merely list them: ``purge`` drops what it lists.

TLS is per provider, and all three default to ``verify-ca``: verify the chain,
skip the name. None of these leaves is reliably issued for the address the
instance is reached at -- a Cloud SQL leaf carries no IP SAN at all -- so
``verify-full`` is available but never assumed.

Where the root comes from is what differs, and it decides what the descriptor
keeps. Cloud SQL signs each instance with a CA of its own, published nowhere, so
the certificate itself is stored -- never a path into somebody's home directory,
which the system could not stay self-contained across nor a domain descriptor
inherit. RDS and Azure publish theirs, so the descriptor keeps the URL
(:attr:`ca_url_key`) and :func:`download_ca` fetches it once per run: a stored
copy would freeze at create while the provider rotates on its own clock.

Either way libpq wants a path, so :meth:`_ca_file` writes the certificate into a
temporary directory for exactly as long as the connection needs it, and
:meth:`data_plane_uri` does the same for the loader -- a domain's model, data and
change sets go over the TLS its system was created with. The path rides only on
tdx's own connections: the URIs in a descriptor carry the mode alone, since a
connector-under-test brings its own root (``$PGSSLROOTCERT``, else
``~/.postgresql/root.crt``).
"""

from __future__ import annotations

import tempfile
import urllib.request
from contextlib import contextmanager
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlencode

from tabsdata_dev.common.core import resources
from tabsdata_dev.common.systems import console, constants, options
from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.hosting.endpoint import Admin
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

# libpq's modes, weakest first. The two that check the server's certificate are
# the ones that need a root cert to check it against.
SSL_MODES = ("disable", "allow", "prefer", "require", "verify-ca", "verify-full")
VERIFYING_SSL_MODES = ("verify-ca", "verify-full")

PEM_HEADER = "-----BEGIN CERTIFICATE-----"

#: tabsdata's cluster-global row-level-security marker. Its `across_projects`
#: policies are granted TO this role, so every schema on the server shares the
#: one role -- which is exactly why a domain may never drop it.
ACROSS_PROJECTS_ROLE = "td_across_projects"

#: One download per URL per run. A published root rotates on the provider's
#: clock, not ours, so nothing is cached between runs -- but a create that
#: probes, then lists, then loads a model should not fetch the same bundle
#: four times.
_CA_DOWNLOADS: dict[str, str] = {}


def download_ca(url: str, what: str) -> str:
    """The PEM at `url`, fetched once per run. Raises when it cannot be had: a
    verifying sslmode with no root is a failure to state, not to work around."""
    if url in _CA_DOWNLOADS:
        return _CA_DOWNLOADS[url]
    console.debug(f"fetching the {what} root CA from {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            pem = response.read().decode("utf-8")
    except OSError as exc:
        raise TdxError(f"could not fetch the {what} root CA from {url}: {exc}") from exc
    if not pem.lstrip().startswith(PEM_HEADER):
        raise TdxError(f"{url} did not return a PEM certificate")
    _CA_DOWNLOADS[url] = pem
    return pem


#: This package, whose resources hold the scripts it sends to its systems.
PACKAGE = "tabsdata_dev.common.systems"


class ManagedPostgres(Postgres):
    slug = ""
    hosting = "managed"
    is_container = False
    # A container's outside plane is docker-only, but this one has nothing to
    # start and probes over SQL instead, so it needs the driver from the outside
    # too (see _venv).
    sys_toolset = constants.TOOLSET_SYSTEMS
    # A managed instance holds a model and its data like any other postgres: the
    # DDL is the plain system's (ddl_from_slug on each provider) and the loader
    # connects over the external plane, with the root certificate materialized
    # for the length of the load (see data_plane_uri).
    supports_models = True
    supports_data = True
    supports_changes = True

    # The default posture, used when the system's meta names no SSLMODE. All
    # three managed providers verify the chain and skip the name: the leaf of a
    # managed instance is not reliably issued for the host it is reached at.
    ssl_mode = "verify-ca"
    #: A provider that PUBLISHES its roots names the meta key holding the URL
    #: they are downloaded from (RDS's bundle, Azure's public roots). One that
    #: does not -- Cloud SQL signs each instance with a CA of its own -- leaves
    #: this empty, and the certificate itself is stored as SERVER_CA_CERT_PEM.
    ca_url_key: str = ""
    ca_url_default: str = ""
    # Role-name prefixes the provider owns: memberships the master is given by
    # the service, never domains. 'pg_' is filtered for every provider.
    role_prefixes: tuple[str, ...] = ()

    # ---- options --------------------------------------------------------

    def connection_options(self) -> tuple[options.Option, ...]:
        """The shared info block, all from ``$<PREFIX>__*`` (as loaded by ``envx
        set-secrets``). A provider appends only its own group.

        Only ``EXTERNAL_HOST`` is required. tdx connects on that one, so without
        it there is nothing to create; ``INTERNAL_HOST`` is the plane tdx cannot
        use and is recorded for whoever runs inside the VPC, so a create is never
        held up for it -- nor for a ``DATABASE`` that is ``postgres`` on every
        instance nobody renamed."""
        p = self.env_prefix
        return (
            options.Option(
                "INTERNAL_HOST",
                "internal-host",
                options.ENV,
                f"env ${p}__INTERNAL_HOST (the private-network plane)",
                required=False,
            ),
            options.Option(
                "EXTERNAL_HOST",
                "external-host",
                options.ENV,
                f"env ${p}__EXTERNAL_HOST",
            ),
            options.Option("PORT", "port", options.ENV, f"env ${p}__PORT"),
            options.Option(
                "DATABASE",
                "database",
                options.SYNTH,
                self.admin_db,
            ),
            options.Option("USER", "user", options.ENV, f"env ${p}__USER"),
            options.Option(
                "PASSWORD",
                "password",
                options.ENV,
                f"env ${p}__PASSWORD",
                secret=True,
            ),
            options.Option("SSLMODE", "sslmode", options.SYNTH, self.ssl_mode),
            # Two ways in, one meta key out: the certificate itself (an env var
            # holding the PEM, as `envx set-secrets` loads it) or a file to read
            # it from. What is stored is always the PEM.
            options.Option(
                "SERVER_CA_CERT_PEM",
                "server-ca-cert-pem",
                options.ENV,
                f"env ${p}__SERVER_CA_CERT_PEM (the certificate itself)",
                required=False,
            ),
            options.Option(
                "SERVER_CA_CERT_PATH",
                "server-ca-cert-path",
                options.ENV,
                f"env ${p}__SERVER_CA_CERT_PATH (a file holding it)",
                required=False,
            ),
        )

    def options(self) -> tuple[options.Option, ...]:
        """The block plus this provider's own group (see ``provider_options``)."""
        return (*self.connection_options(), *self.provider_options())

    def provider_options(self) -> tuple[options.Option, ...]:
        """What only this provider has -- the AWS / GCP / AZ group. All
        informational: the instance is reached at its host, so a create is never
        held up for any of them."""
        return ()

    def provider_option(self, name: str, doc: str) -> options.Option:
        """One informational provider option, named the way its group is."""
        return options.Option(
            name,
            name.lower().replace("_", "-"),
            options.ENV,
            f"env ${self.env_prefix}__{name} ({doc})",
            required=False,
        )

    def synth_default(self, name: str, sys_name: str) -> str:
        if name == "SSLMODE":
            return self.ssl_mode
        if name == "DATABASE":
            return self.admin_db
        if name and name == self.ca_url_key:
            return self.ca_url_default
        raise TdxError(f"{self.slug}: no synth default for {name}")

    def ca_url_option(self, doc: str) -> options.Option:
        """The URL the provider publishes its root at, as an option: it lands in
        the descriptor (so `info` says which root this system trusts) and in the
        vault item (so an instance behind a different root is a field rather than
        a code change), defaulting to the one published today."""
        return options.Option(
            self.ca_url_key,
            self.ca_url_key.lower().replace("_", "-"),
            options.SYNTH,
            f"{self.ca_url_default} ({doc})",
            required=False,
        )

    def docker_images(self) -> list[tuple[str, str]]:
        return []

    # ---- connection -----------------------------------------------------

    def _sslmode(self, meta: dict[str, str]) -> str:
        return meta.get("SSLMODE") or self.ssl_mode

    def _ca_pem(self, meta: dict[str, str]) -> str:
        """The root certificate a verifying mode validates against, as PEM text,
        or ``""`` when there is none.

        A certificate handed in directly always wins -- the escape hatch for an
        instance whose root is neither published nor Cloud SQL's. Failing that, a
        provider with ``ca_url_key`` downloads the root it publishes, which is
        why those descriptors keep a URL and not a certificate: a stored copy
        freezes at create while the provider rotates on its own clock.
        """
        stored = meta.get("SERVER_CA_CERT_PEM", "")
        if stored:
            return stored
        if not self.ca_url_key:
            return ""
        # Present and empty is a decision -- somebody blanked the field to say
        # "not from there" -- and is answered with the refusal, not with the
        # built-in URL behind their back. Absent is a descriptor written before
        # the URL existed, which the published root is the right answer for.
        url = meta.get(self.ca_url_key, self.ca_url_default)
        return download_ca(url, self.label) if url else ""

    def _read_ca(self, meta: dict[str, str]) -> None:
        """Resolve the two inputs into ``SERVER_CA_CERT_PEM`` -- the certificate
        itself, which is what the descriptor keeps. A path is read here, at
        create, so nothing later depends on that file still being there (or on
        this machine); it is then dropped, for the same reason the vault never
        carries it -- a path into somebody's home directory describes one box, so
        keeping it in the meta would offer every reader of the descriptor a file
        that is not theirs."""
        pem = meta.get("SERVER_CA_CERT_PEM", "")
        path = meta.get("SERVER_CA_CERT_PATH", "")
        if pem and path:
            raise TdxError(
                f"{self.slug}: specify the server CA once — --server-ca-cert-pem "
                f"(the PEM) or --server-ca-cert-path (a file holding it), not both"
            )
        if path:
            src = Path(path).expanduser()
            if not src.is_file():
                raise TdxError(
                    f"{self.slug}: --server-ca-cert-path '{path}' is not a file"
                )
            pem = src.read_text(encoding="utf-8")
        if pem and not pem.lstrip().startswith(PEM_HEADER):
            where = (
                f"--server-ca-cert-path '{path}'" if path else "--server-ca-cert-pem"
            )
            raise TdxError(f"{self.slug}: {where} is not a PEM certificate")
        # Canonical form: a file keeps its trailing newline and `$(cat ...)` eats
        # it, and the same certificate arriving two ways must not become two
        # stored values (and two content-addressed files).
        meta["SERVER_CA_CERT_PEM"] = f"{pem.strip()}\n" if pem else ""
        meta.pop("SERVER_CA_CERT_PATH", None)

    def _check_ssl(self, meta: dict[str, str]) -> None:
        """Refuse a TLS setting the instance cannot honour, at create time --
        libpq reports these as a bare ``certificate verify failed`` much later,
        and neither is guessable from that."""
        mode = self._sslmode(meta)
        if mode not in SSL_MODES:
            raise TdxError(
                f"{self.slug}: unknown sslmode '{mode}' — one of: "
                f"{', '.join(SSL_MODES)}"
            )
        if mode not in VERIFYING_SSL_MODES:
            return
        if not self._ca_pem(meta):
            raise TdxError(self.missing_ca_message(meta, mode))

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        """What to say when a verifying mode has no root to verify against. Each
        provider names where its certificate comes from, so the refusal is a
        command to run rather than a shrug."""
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server, so it needs the "
            f"instance's root CA — pass --server-ca-cert-path FILE (or hand the "
            f"PEM itself in ${self.env_prefix}__SERVER_CA_CERT_PEM).\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )

    @contextmanager
    def _ca_file(self, admin: Admin):
        """`admin` with ``sslrootcert`` pointing at its certificate on disk, for
        the length of the block and no longer.

        ``sslrootcert`` takes a path, but a path is not what tdx has -- it has the
        certificate. Nothing is left behind between commands: the file is written
        into a temporary directory that goes when the connection that needed it
        does, so there is no cache to go stale after a CA rotation and nothing for
        a destroy to clean up."""
        if not admin.ca_pem:
            yield admin
            return
        with tempfile.TemporaryDirectory(prefix="tdx-ca-") as tmp:
            path = Path(tmp) / "server-ca.pem"
            path.write_text(admin.ca_pem, encoding="utf-8")
            yield replace(admin, sslrootcert=str(path))

    def _run_admin(self, admin: Admin, statements: list[str]) -> None:
        with self._ca_file(admin) as connectable:
            super()._run_admin(connectable, statements)

    def _query_admin(self, admin: Admin, query: str) -> list[str]:
        with self._ca_file(admin) as connectable:
            return super()._query_admin(connectable, query)

    def _with_ssl(self, url: str, sslmode: str, sslrootcert: str = "") -> str:
        """Add the TLS settings to a URL that carries none. Never call it on a
        URL that already has them: libpq reads a repeated parameter as a list
        and rejects the pair (`invalid sslmode value: "('verify-full',
        'verify-full')"`). To add only the root cert, use _with_root_cert."""
        params = {"sslmode": sslmode}
        if sslrootcert:
            params["sslrootcert"] = sslrootcert
        return self._add_params(url, params)

    @staticmethod
    def _add_params(url: str, params: dict[str, str]) -> str:
        sep = "&" if "?" in url else "?"
        return f"{url}{sep}{urlencode(params)}"

    def _with_root_cert(self, url: str, sslrootcert: str) -> str:
        """A *recorded* URI plus the path to the root certificate. The mode is
        already on it (``finish_uri`` put it there when the descriptor was
        written), so only the path is added."""
        return self._add_params(url, {"sslrootcert": sslrootcert})

    def _admin_url(self, admin: Admin) -> str:
        return self._with_ssl(
            super()._admin_url(admin),
            admin.sslmode or self.ssl_mode,
            admin.sslrootcert,
        )

    def finish_uri(self, url: str, meta: dict[str, str]) -> str:
        return self._with_ssl(url, self._sslmode(meta))

    def _admin(self, sys_meta: dict[str, str]) -> Admin:
        return replace(
            super()._admin(sys_meta),
            sslmode=self._sslmode(sys_meta),
            ca_pem=self._ca_pem(sys_meta),
        )

    def _probe(self, meta: dict[str, str]) -> None:
        self._query_admin(self._admin(meta), "SELECT 1")

    @contextmanager
    def data_plane_uri(self, meta: dict[str, str]):
        """The external plane's URI with ``sslrootcert`` pointing at the
        certificate on disk, for the length of the load and no longer.

        The loader goes through ``run_sql_text``, which takes a URI and nothing
        else, while a verifying ``sslmode`` needs libpq to be handed a path. So
        the same temporary file the admin connections get is written here too --
        the recorded URIs stay free of a path that belongs to one machine."""
        uri = meta.get("EXTERNAL_SQLALCHEMY_URI", "")
        pem = self._ca_pem(meta)
        if not pem or self._sslmode(meta) not in VERIFYING_SSL_MODES:
            yield uri
            return
        with tempfile.TemporaryDirectory(prefix="tdx-ca-") as tmp:
            path = Path(tmp) / "server-ca.pem"
            path.write_text(pem, encoding="utf-8")
            yield self._with_root_cert(uri, str(path))

    # ---- system lifecycle (the instance is externally owned) ------------

    def plan_system(
        self, name: str, overrides: dict[str, str] | None = None
    ) -> dict[str, str]:
        o = overrides or {}
        # Built in the order a reader wants it: the block every one of the five
        # shares, then this provider's own group, then the URIs derived from both.
        meta = {opt.name: o.get(opt.name, "") for opt in self.connection_options()}
        meta["DATABASE"] = meta.get("DATABASE") or self.admin_db
        self._read_ca(meta)
        meta["VERSION"] = ""  # filled in by the probe, once there is a server to ask
        meta.update({opt.name: o.get(opt.name, "") for opt in self.provider_options()})
        # After the provider group: a refusal names the instance from it, so it
        # can print the command that fetches the certificate rather than a
        # placeholder somebody has to notice and replace.
        self._check_ssl(meta)
        self._plane_keys(meta, meta["DATABASE"], meta["USER"], meta["PASSWORD"])
        return meta

    def provision_system(
        self, meta: dict[str, str], *, force: bool = False
    ) -> dict[str, str]:
        self._probe(meta)
        return {"VERSION": self._probe_version(meta)}

    def destroy_system(self, meta: dict[str, str]) -> None:
        return None

    def system_status(self, meta: dict[str, str]) -> tuple[bool, str]:
        try:
            self._probe(meta)
        except TdxError as exc:
            return False, f"cannot reach {self.label}: {exc}"
        where = self._admin(meta)
        return True, f"{self.label} at {where.host}:{where.port}"

    # ---- domain lifecycle (a database + its owner) ----------------------

    def provider_meta(self, sys_meta: dict[str, str]) -> dict[str, str]:
        """No docker keys on an instance nobody runs -- the TLS pair instead, so
        a domain descriptor can reach the instance without the system's, plus
        this provider's own group."""
        meta = {
            "SSLMODE": self._sslmode(sys_meta),
            "SERVER_CA_CERT_PEM": sys_meta.get("SERVER_CA_CERT_PEM", ""),
        }
        meta.update({o.name: sys_meta.get(o.name, "") for o in self.provider_options()})
        return meta

    def create_domain_sql(self, db: str, user: str, password: str) -> list[str]:
        # The marker exists once per server and is granted WITH ADMIN OPTION, so
        # tabsdata's dbmanager -- which connects as this domain's own user, not
        # as an administrator -- can grant it onward to the per-schema roles it
        # creates. Without it `db upgrade` refuses: only a role holding ADMIN on
        # a cluster-global role may grant it, so the server's owner has to, and
        # on a managed instance that is us. Creating it here rather than leaving
        # it to whoever runs first also makes the ownership deliberate.
        return [
            f"CREATE USER \"{user}\" WITH PASSWORD '{password}' CREATEROLE",
            f'GRANT "{user}" TO CURRENT_USER',
            f'CREATE DATABASE "{db}" OWNER "{user}"',
            f'GRANT ALL PRIVILEGES ON DATABASE "{db}" TO "{user}"',
            resources.render(
                PACKAGE,
                "postgres/across_projects_role.sql",
                role=ACROSS_PROJECTS_ROLE,
            ),
            f'GRANT "{ACROSS_PROJECTS_ROLE}" TO "{user}" WITH ADMIN OPTION',
        ]

    def delete_domain_sql(self, name: str) -> list[str]:
        # No '%' in any statement: the driver would read it as a placeholder.
        user = self._login(name)
        # The per-schema roles tabsdata created under this domain -- and only
        # those; dropping the shared ACROSS_PROJECTS_ROLE would take every
        # other domain's row-level security with it. The template says how.
        drop_administered_roles = resources.render(
            PACKAGE,
            "postgres/drop_administered_roles.sql",
            user=user,
        )
        return [
            f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)',
            drop_administered_roles,
            f'DROP USER IF EXISTS "{user}"',
        ]

    def list_schemas_sql(self) -> str:
        skips = "".join(
            f"AND NOT starts_with(r.rolname, '{p}') "
            for p in (*self.role_prefixes, "pg_")
        )
        return (
            "SELECT datname FROM pg_database "
            "WHERE datistemplate = false AND datname <> 'postgres' "
            "UNION "
            "SELECT r.rolname FROM pg_auth_members m "
            "JOIN pg_roles r ON r.oid = m.roleid "
            "WHERE m.member = (SELECT oid FROM pg_roles WHERE rolname = CURRENT_USER) "
            f"{skips}"
            "ORDER BY 1"
        )
