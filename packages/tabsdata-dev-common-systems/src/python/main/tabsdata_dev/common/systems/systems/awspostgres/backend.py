#
# Copyright 2026 Tabsdata Inc.
#

"""AWS RDS PostgreSQL backend — a managed remote instance, provisioning-only.

The provider half of :class:`ManagedPostgres`, which holds everything this shares
with Cloud SQL: nothing to start, a domain is a DATABASE owned by a dedicated
role, and the master is not a superuser. ``create`` only reads the connection
from the ``AWSPOSTGRES__`` environment (EXTERNAL_HOST / PORT / USER / PASSWORD,
as loaded by ``envx set-secrets``) and probes it. ``AWS_ACCOUNT_ID`` and
``AWS_REGION`` are read the same way but are informational -- the instance is
reached at its host, so a create is never held up for either.

What is AWS's own: ``rdsadmin`` is RDS's maintenance database and ``rds_*`` are
its service roles -- neither is ever a domain -- and the TLS root. RDS server
certificates chain to Amazon's own root CAs, which are not in the public trust
store, so ``sslmode=verify-full`` validates against the AWS global bundle,
downloaded to ``/tmp`` the first time a run needs it. Nothing is kept between
runs, so the bundle is always a current one (AWS rotates these); that throwaway
path stays out of the descriptor's URIs.
"""

from __future__ import annotations

import urllib.request

from tabsdata_dev.common.systems.errors import TdxError
from tabsdata_dev.common.systems.systems._common.managed_postgres import (
    PEM_HEADER,
    ManagedPostgres,
)
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres

CA_BUNDLE_URL = "https://truststore.pki.rds.amazonaws.com/global/global-bundle.pem"


class AwsPostgres(ManagedPostgres):
    slug = "awspostgres"
    label = "AWS RDS PostgreSQL"
    env_prefix = "AWSPOSTGRES"
    ssl_mode = "verify-full"
    # rdsadmin is RDS's own maintenance database — never a domain.
    system_schemas = Postgres.system_schemas | {"rdsadmin"}
    role_prefixes = ("rds_",)
    # A model is the plain system's; only the server differs.
    ddl_from_slug = "postgres"
    # The vault carries no certificate for this one: the bundle is a download.
    onepassword_skip = ("SERVER_CA_CERT_PEM", "SERVER_CA_CERT_PATH")

    _ca_bundle: str = ""

    def provider_options(self):
        return (
            self.provider_option("AWS_ACCOUNT_ID", "the account the instance is in"),
            self.provider_option("AWS_REGION", "the region it runs in"),
        )

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        # Unreachable in practice -- _ca_pem downloads rather than returning ""
        # -- but a network that refuses the download must still say where to look.
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server and the RDS CA "
            f"bundle could not be fetched from {CA_BUNDLE_URL}\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )

    def _ca_pem(self, meta: dict[str, str]) -> str:
        """The RDS root CA bundle ``sslmode=verify-full`` validates against:
        downloaded the first time a run needs it, held for the rest of that run
        and never kept beyond it, so the bundle is always a current one."""
        if self._ca_bundle:
            return self._ca_bundle
        print(f">>> fetching the RDS CA bundle from {CA_BUNDLE_URL} …", flush=True)
        try:
            with urllib.request.urlopen(CA_BUNDLE_URL, timeout=30) as resp:  # noqa: S310
                pem = resp.read().decode("utf-8")
        except OSError as exc:
            raise TdxError(
                f"could not fetch the RDS CA bundle from {CA_BUNDLE_URL} "
                f"(needed for sslmode={self.ssl_mode}): {exc}"
            ) from exc
        if not pem.lstrip().startswith(PEM_HEADER):
            raise TdxError(f"{CA_BUNDLE_URL} did not return a PEM bundle")
        self._ca_bundle = pem
        return pem
