#
# Copyright 2026 Tabsdata Inc.
#

"""GCP Cloud SQL PostgreSQL backend — a managed remote instance, provisioning-only.

The provider half of :class:`ManagedPostgres`, which holds everything this shares
with RDS and Azure: nothing to start, a domain is a DATABASE owned by a dedicated
role, and the master (``postgres``, a member of ``cloudsqlsuperuser``) is not a
superuser. ``create`` only reads the connection from the ``GCPPOSTGRES__``
environment (EXTERNAL_HOST / PORT / USER / PASSWORD, as loaded by ``envx
set-secrets``) and probes it. ``GCP_PROJECT``, ``GCP_REGION``, ``GCP_INSTANCE_ID``
and ``INTERNAL_HOST`` are read the same way but are informational -- tdx reaches
the instance at its external host, so a create is never held up for any of them.
``GCP_PROJECT`` and ``GCP_INSTANCE_ID`` are what name the instance to ``gcloud``,
so they are what the missing-CA refusal quotes.

What is Google's own: ``cloudsqladmin`` is Cloud SQL's maintenance database and
``cloudsql*`` are its service roles -- ``cloudsqlsuperuser`` is one the master
holds, so without the prefix filter a listing would offer it as a domain and a
purge would drop it -- and the TLS root.

**TLS.** Nothing about a Cloud SQL certificate can be assumed from the RDS case,
which is why the mode is the system's rather than the class's:

- The leaf is issued by a **per-instance** ``Cloud SQL Server CA``, which lives
  in the instance resource itself (``serverCaCert.cert``, self-signed) -- there
  is no bundle to download the way RDS publishes one. It is fetched once::

      gcloud sql instances describe INSTANCE --project PROJECT \
          --format='value(serverCaCert.cert)' > server-ca.pem

  and handed to create either way round: ``--server-ca-cert-path server-ca.pem``,
  or the certificate itself in ``$GCPPOSTGRES__SERVER_CA_CERT_PEM``. Either way
  what the descriptor stores is the certificate, not the path -- every later
  connection (status, domain create, a model's data, destroy, purge) needs it,
  and a path into somebody's home directory is not something a domain descriptor
  can inherit. A connection that needs a path gets one written to a temporary
  directory for the length of that connection. The cost is that the stored copy
  is frozen at create: rotating the instance's CA means ``system create --force``,
  which is only a probe.

- The leaf names the instance (CN ``project:instance``, SAN
  ``<uid>.<region>.sql.goog``) and carries **no IP SAN**, so ``verify-full``
  against a public IP fails the name check however good the root is. Hence the
  default of ``verify-ca``, which verifies the chain and skips the name; keep
  ``verify-full`` only with the ``.sql.goog`` name as EXTERNAL_HOST.

``--sslmode require`` encrypts without verifying and needs no cert -- available,
never the default.
"""

from __future__ import annotations

from tabsdata_dev.common.systems import options
from tabsdata_dev.common.systems.systems.postgres.backend import Postgres
from tabsdata_dev.common.systems.systems.postgres.managed import ManagedPostgres


class GcpPostgres(ManagedPostgres):
    slug = "gcppostgres"
    label = "GCP Cloud SQL PostgreSQL"
    env_prefix = "GCPPOSTGRES"
    # The certificate names the instance, not the host it is reached at.
    ssl_mode = "verify-ca"
    # cloudsqladmin is Cloud SQL's own maintenance database — never a domain.
    system_schemas = Postgres.system_schemas | {"cloudsqladmin"}
    role_prefixes = ("cloudsql",)
    # A model is the plain system's; only the server differs.
    ddl_from_slug = "postgres"
    # The vault carries the certificate, never the path to a copy of it: that
    # path is one machine's, and an item holding both would be refused at create.
    onepassword_skip = ("SERVER_CA_CERT_PATH",)

    def provider_options(self) -> tuple[options.Option, ...]:
        # The three halves of `project:region:instance`, in Google's terms --
        # `tabsdata-dev`, `europe-west1`, `k8sdb`. None is part of reaching the
        # instance (that is the host), but together they name it to `gcloud`,
        # which is where its server CA comes from, so the refusal below can say
        # the command to run rather than a placeholder.
        return (
            self.provider_option("GCP_PROJECT", "the project the instance is in"),
            self.provider_option("GCP_REGION", "the region it runs in"),
            self.provider_option("GCP_INSTANCE_ID", "the Cloud SQL instance"),
        )

    def missing_ca_message(self, meta: dict[str, str], mode: str) -> str:
        project = meta.get("GCP_PROJECT", "")
        return (
            f"{self.slug}: sslmode '{mode}' verifies the server, so it needs the "
            f"instance's own CA — Cloud SQL signs each instance with a CA of its "
            f"own, and there is no bundle to download. Fetch it once:\n"
            f"  gcloud sql instances describe "
            f"{meta.get('GCP_INSTANCE_ID') or 'INSTANCE'}"
            # Left off when unknown rather than guessed: gcloud falls back to the
            # configured project, which is right more often than a placeholder
            # somebody has to notice and replace.
            f"{f' --project {project}' if project else ''} "
            f"--format='value(serverCaCert.cert)' > server-ca.pem\n"
            f"then pass --server-ca-cert-path server-ca.pem (or hand the PEM "
            f"itself in ${self.env_prefix}__SERVER_CA_CERT_PEM).\n"
            f"(or --sslmode require to encrypt without verifying the server)"
        )
