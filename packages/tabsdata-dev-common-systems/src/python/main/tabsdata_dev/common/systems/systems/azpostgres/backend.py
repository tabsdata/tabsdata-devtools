#
# Copyright 2026 Tabsdata Inc.
#

"""Azure Database for PostgreSQL Flexible Server — a managed remote instance.

The third provider half of :class:`ManagedPostgres`, alongside RDS and Cloud SQL:
nothing to start, a domain is a DATABASE owned by a dedicated role, and the
administrator is not a superuser. ``create`` only reads the connection from the
``AZPOSTGRES__`` environment (EXTERNAL_HOST / PORT / USER / PASSWORD, as loaded
by ``envx set-secrets``) and probes it. ``AZ_SERVER_NAME`` and ``AZ_REGION`` are
read the same way but are informational -- the server is reached at its host, so
a create is never held up for either.

**Flexible Server, not Single Server.** The two differ in the one place that
would break a login: Single Server wanted ``user@server`` as the username, while
Flexible Server takes the plain administrator name, which is what ``USER`` holds.
Flexible Server is also the only one Azure still sells.

What is Azure's own: ``azure_maintenance`` and ``azure_sys`` are the service
databases (never domains), and ``azure_*`` are the roles the service grants the
administrator -- ``azure_pg_admin`` is one it holds, so without the prefix filter
a listing would offer it as a domain and a purge would drop it.

**TLS.** Unlike Cloud SQL, an Azure leaf carries the server's own name
(``<server>.postgres.database.azure.com``) as a SAN, so ``verify-full`` is the
default and works against the host you actually connect to. What it needs is the
root: Azure signs with public CAs (DigiCert Global Root G2 and Microsoft RSA Root
CA 2017 at the time of writing) which libpq will not find on its own, so the root
is supplied the same way Cloud SQL's is -- ``--server-ca-cert-path FILE``, or the
PEM itself in ``$AZPOSTGRES__SERVER_CA_CERT_PEM`` -- and the descriptor stores
the certificate rather than a path belonging to one machine. Azure rotates these
and publishes the current ones; the stored copy is frozen at create, so a
rotation means ``system create --force``, which is only a probe.

``--sslmode require`` encrypts without verifying and needs no cert -- available,
never the default.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.managed_postgres import ManagedPostgres
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

# Where Azure publishes the roots its servers chain to.
CA_DOC_URL = (
    "https://learn.microsoft.com/azure/postgresql/flexible-server/"
    "concepts-networking-ssl-tls"
)


class AzPostgres(ManagedPostgres):
    slug = "azpostgres"
    label = "Azure Database for PostgreSQL"
    env_prefix = "AZPOSTGRES"
    # The leaf carries the server's name, so the strict mode is the useful one.
    ssl_mode = "verify-full"
    # Azure's own service databases — never domains.
    system_schemas = Postgres.system_schemas | {"azure_maintenance", "azure_sys"}
    role_prefixes = ("azure_",)
    # A model is the plain system's; only the server differs.
    ddl_from_slug = "postgres"
    # The vault carries the certificate, never the path to a copy of it: that
    # path is one machine's, and an item holding both would be refused at create.
    onepassword_skip = ("SERVER_CA_CERT_PATH",)

    def provider_options(self) -> tuple[options.Option, ...]:
        # Which server this is, in Azure's terms. Not part of reaching it (that
        # is the host, `<server>.postgres.database.azure.com`), but it is what
        # names the server to `az postgres flexible-server`.
        return (
            self.provider_option("AZ_SERVER_NAME", "the flexible server"),
            self.provider_option("AZ_REGION", "the region it runs in"),
        )

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        server = meta.get("AZ_SERVER_NAME") or "SERVER"
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server, so it needs the "
            f"root Azure signs '{server}' with — a public CA that libpq will not "
            f"find on its own. Download the current root(s) from\n"
            f"  {CA_DOC_URL}\n"
            f"then pass --server-ca-cert-path FILE (or hand the PEM itself in "
            f"${self.env_prefix}__SERVER_CA_CERT_PEM).\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )
