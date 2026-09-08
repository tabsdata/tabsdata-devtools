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
(``<server>.postgres.database.azure.com``) as a SAN, so the host it is reached at
is one the certificate names. What it needs is the root: Azure signs with public
CAs (DigiCert Global Root G2 today, Microsoft RSA Root CA 2017 for some servers)
which libpq will not find on its own. So the descriptor keeps the URL Azure
publishes the root at (``AZ_SERVER_CA_CERT_PEM_URL``) and not a copy of it --
Azure rotates these, and a copy taken at create is the one thing that goes stale
without anyone touching it. It is downloaded once per run and written to a
temporary file for exactly as long as a connection needs it. A server behind the
other root is a field in the vault item, not a code change; a PEM handed in
directly still wins over the download.

``--sslmode require`` encrypts without verifying and needs no cert -- available,
never the default. ``verify-full`` is available too and does work here, the leaf
being named for the host; ``verify-ca`` is the default the three managed
providers share.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.managed_postgres import ManagedPostgres
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

#: The root Azure signs a flexible server with today. A server on the other one
#: (Microsoft RSA Root CA 2017) is a different URL in the item, not a patch.
CA_PEM_URL = "https://cacerts.digicert.com/DigiCertGlobalRootG2.crt.pem"
# Where Azure documents which roots its servers chain to.
CA_DOC_URL = (
    "https://learn.microsoft.com/azure/postgresql/flexible-server/"
    "concepts-networking-ssl-tls"
)


class AzPostgres(ManagedPostgres):
    slug = "azpostgres"
    label = "Azure Database for PostgreSQL"
    env_prefix = "AZPOSTGRES"
    # Azure's own service databases — never domains.
    system_schemas = Postgres.system_schemas | {"azure_maintenance", "azure_sys"}
    role_prefixes = ("azure_",)
    # A model is the plain system's; only the server differs.
    ddl_from_slug = "postgres"
    # Azure publishes its roots, so the descriptor keeps the URL and not a copy.
    ca_url_key = "AZ_SERVER_CA_CERT_PEM_URL"
    ca_url_default = CA_PEM_URL
    # The vault carries neither the certificate nor a path to one: the root is a
    # download, and a path is one machine's.
    onepassword_skip = ("SERVER_CA_CERT_PEM", "SERVER_CA_CERT_PATH")

    def provider_options(self) -> tuple[options.Option, ...]:
        # Which server this is, in Azure's terms. Not part of reaching it (that
        # is the host, `<server>.postgres.database.azure.com`), but it is what
        # names the server to `az postgres flexible-server`.
        return (
            self.ca_url_option("the root Azure signs a flexible server with"),
            self.provider_option("AZ_SERVER_NAME", "the flexible server"),
            self.provider_option("AZ_REGION", "the region it runs in"),
        )

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        # Reached only when the URL is blanked out: with one, _ca_pem downloads
        # and raises with the URL in it rather than returning nothing.
        server = meta.get("AZ_SERVER_NAME") or "SERVER"
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server, so it needs the "
            f"root Azure signs '{server}' with — a public CA that libpq will not "
            f"find on its own. Leave --az-server-ca-cert-pem-url at {CA_PEM_URL}, "
            f"or set it to the root this server uses (Azure lists them at\n"
            f"  {CA_DOC_URL} ),\n"
            f"or hand the PEM itself in ${self.env_prefix}__SERVER_CA_CERT_PEM.\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )
