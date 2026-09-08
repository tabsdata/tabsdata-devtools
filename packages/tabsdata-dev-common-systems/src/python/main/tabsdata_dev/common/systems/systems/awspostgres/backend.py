#
# Copyright 2026 Tabsdata Inc.
#

"""AWS RDS PostgreSQL backend — a managed remote instance, provisioning-only.

The provider half of :class:`ManagedPostgres`, which holds everything this shares
with Cloud SQL and Azure: nothing to start, a domain is a DATABASE owned by a
dedicated role, and the master is not a superuser. ``create`` only reads the
connection from the ``AWSPOSTGRES__`` environment (EXTERNAL_HOST / PORT / USER /
PASSWORD, as loaded by ``envx set-secrets``) and probes it. ``AWS_ACCOUNT_ID``,
``AWS_REGION`` and ``AWS_DB_INSTANCE`` are read the same way but are
informational -- the instance is reached at its host, so a create is never held
up for any of them, and they are what name it to the ``aws`` CLI.

What is AWS's own: ``rdsadmin`` is RDS's maintenance database and ``rds_*`` are
its service roles -- neither is ever a domain -- and the TLS root. RDS server
certificates chain to Amazon's own root CAs, which libpq will not find in the
public trust store, so what the descriptor keeps is the URL AWS publishes its
global bundle at (``AWS_SERVER_CA_CERT_PEM_URL``) rather than a copy of the
bundle: AWS rotates these, and a copy taken at create would be the one thing
that goes stale without anyone touching it. It is downloaded once per run and
written to a temporary file for exactly as long as a connection needs it, so
that path never reaches a descriptor's URIs.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems._common.managed_postgres import ManagedPostgres
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

#: Every region's root in one file -- what AWS tells you to trust, and what an
#: instance moved between regions keeps working against.
CA_BUNDLE_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"


class AwsPostgres(ManagedPostgres):
    slug = "awspostgres"
    label = "AWS RDS PostgreSQL"
    env_prefix = "AWSPOSTGRES"
    # rdsadmin is RDS's own maintenance database — never a domain.
    system_schemas = Postgres.system_schemas | {"rdsadmin"}
    role_prefixes = ("rds_",)
    # A model is the plain system's; only the server differs.
    ddl_from_slug = "postgres"
    # AWS publishes its roots, so the descriptor keeps the URL and not a copy.
    ca_url_key = "AWS_SERVER_CA_CERT_PEM_URL"
    ca_url_default = CA_BUNDLE_URL
    # The vault carries no certificate for this one: the bundle is a download,
    # and a path is one machine's.
    onepassword_skip = ("SERVER_CA_CERT_PEM", "SERVER_CA_CERT_PATH")

    def provider_options(self) -> tuple[options.Option, ...]:
        return (
            self.ca_url_option("the RDS global bundle"),
            self.provider_option("AWS_ACCOUNT_ID", "the account the instance is in"),
            self.provider_option("AWS_REGION", "the region it runs in"),
            self.provider_option("AWS_DB_INSTANCE", "the RDS instance identifier"),
        )

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        # Reached only when the URL is blanked out: with one, _ca_pem downloads
        # and raises with the URL in it rather than returning nothing.
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server, so it needs the "
            f"RDS root CA — leave --aws-server-ca-cert-pem-url at {CA_BUNDLE_URL}, "
            f"or hand a PEM in ${self.env_prefix}__SERVER_CA_CERT_PEM.\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )
