<!--
Copyright 2026 Tabsdata Inc.
-->

# tabsdata-dev-common-systems

The system / domain family, ported from tabsdata-os devutils (`tdx-system`/`tdx-domain`): ~30
backends (docker-run and compose databases, object stores, warehouses, kafka, credential-only
services), encrypted descriptors, YAML manifests, a batch runner, deterministic data generation
with per-system DDL. The tools `system`, `domain` and `domain-sf` are thin entry points over it.

## Shape

- `dispatch.py`/`main.py` -- the CLI over the backend registry; `descriptor`, `crypto`,
  `manifest`, `store`, `naming`, `options`; `batch`, `console`, `datagen`, `sql_runner`.
- `systems/<slug>/backend.py` -- one backend each, plus `domain/` overrides and
  `models/<name>/*.ddl`; `models/<name>/` -- entities, generators, data files (parsed data:
  csv/ddl carry no header). `protocols.py` is the structural contract they satisfy: a command
  module gets one as `ctx.system` and calls those methods, so a new system is a class
  implementing the Protocol plus its command files.
- Two shared bases under `systems/_common/` carry everything a family has in common, so a
  backend is only what differs -- see below.
- Ranges on pydantic, pyyaml, cryptography; joins only the toolsets whose tools depend on it.

## How it works

- Descriptors under `<tdd_dir>/data/system` and `data/domain` are encrypted with
  `_TDD_CRYPTO_KEY` (`tdd env set --crypto`; 1Password field `TD_BACKENDS_CRYPTO_KEY`).
  A shell still exporting the old name is told what to run.
- A backend names the toolset each plane needs (`sys_toolset`/`dom_toolset`); when a domain verb
  belongs to another toolset, `domain` re-dispatches through `tdd-exe` to `domain-sf`.
- A system's own config comes from `<SYSTEM>__<KEY>` variables (`S3__BUCKET`,
  `DRUID__ROUTER_PORT`); `secrets` loads them from 1Password.
- Every verb describes its own options once, and `config` reads that: a delegated verb through
  its command module's `add_arguments`, a common one through the parser builder its handler uses
  (`dispatch.common_parsers`). That is what keeps `config --show` and the config file from
  drifting from the CLI -- the ten verbs handled in `dispatch` had no table at all while their
  parsers were built inline.
- Output follows the guidelines through the `console` adapter; chatty verbs log to
  `/tmp/tdd-<tool>-<verb>-<name>-<stamp>.log`, which is also the failure log.
- `diagnostics.py`: what the database said, for that log. Every SQL failure path
  (`sql_runner`, the backends' `_run_admin`/`_query_admin`) attaches `db_failure()` to the
  `TdxError` -- SQLSTATE, the server's DETAIL/HINT/CONTEXT, the schema/table/constraint it
  named, the failing statement, the target with the password stripped. The one line a person
  reads is the driver's summary; the answer is almost always in what the summary dropped.
- Domain names are `<user>_<build>` from `TD_BUILD_USER`/`TD_BUILD_NUMBER` (else login/0).
- Host ports: every system type owns a slot of 100 from 20000, by registry order (append-only);
  a create walks its slot for free ports, `--ports` pins them --
  [docs/ports.md](../../docs/ports.md).
- Docker containers are named from one constant (`DOCKER_CONTAINER_PREFIX`, `tdd`), which is what
  `clean-docker` matches; `tdx2` survives only where it means the legacy descriptor format.

## The two backend bases

All five postgres types hand a new domain's owner the `public` schema of its own database
(`ALTER SCHEMA public OWNER TO`, on a connection to that database). Creating a database owned by a
role is not enough to let it put a table there: since PostgreSQL 15 `public` belongs to
`pg_database_owner` -- implicitly the database's owner, which is why a stock server and Cloud SQL
appear to need nothing -- while Azure Flexible Server's template gives it to `azure_pg_admin` and
everyone else USAGE alone. Saying it outright makes the five behave alike on any server.

**`SqlContainerBackend`** (`_common/sql.py`) for the docker-container SQL databases -- mysql,
postgres, oracle, db2, mssqlserver, clickhouse, starrocks. A subclass supplies only its dialect
hooks: image and server flags, the readiness probe, the SQLAlchemy driver and identifier quote,
the create/drop-domain SQL and the schema-listing query, and the server's own schemas that must
never be read as domains. The container lifecycle, TCP admin over SQLAlchemy, per-domain
provisioning, model and data loading and delta application live here once. A model is available
for a system exactly when `<slug>/domain/models/<model>/<slug>.ddl` exists, which is what lets the
generic `models`/`create-model`/`create-data`/`modify-data` serve every dialect.

**`ManagedPostgres`** (`_common/managed_postgres.py`) for provider-managed PostgreSQL -- AWS RDS
(`awspostgres`), GCP Cloud SQL (`gcppostgres`), Azure Flexible Server (`azpostgres`). They differ
in almost nothing the toolkit cares about: nothing runs locally, so `create` reads the connection
from the `<SYSTEM>__` environment and probes it, and the master user is **not** a superuser, which
is what shapes the DDL. A domain is a DATABASE owned by a dedicated role, and a non-superuser
master may only create a database owned by a role it belongs to -- so the owner role is created and
granted to the master *before* the database, and gets `CREATEROLE` so a test can add roles of its
own. Dropping a domain therefore drops the roles the owner administers between the database and the
owner: it is their recorded grantor and (PostgreSQL 16+) cannot be dropped while they exist.

Two consequences worth keeping in view. Owner roles the master belongs to are listed as domain
entities, so a purge that died half way leaves a visible remnant that the next purge cleans rather
than an invisible one a create collides with. And that same listing is why a subclass must declare
its provider's `role_prefixes` (`rds_*`, `cloudsql*`, `azure_*`): those memberships are the
service's, not domains, and **purge drops what it lists**.

TLS is the per-provider part, and all three default to **`verify-ca`**: verify the chain, skip the
name. None of these leaves is reliably issued for the address the instance is reached at -- a Cloud
SQL leaf carries no IP SAN at all -- so `verify-full` is available but never assumed.

Where the root comes from is what actually differs, and it decides what the descriptor keeps. Cloud
SQL signs each instance with a CA of its own, published nowhere: the **certificate itself** is
stored (`SERVER_CA_CERT_PEM`), never a path, because a path into one machine's home directory is
not something a domain descriptor can inherit. RDS and Azure publish theirs, so what is stored is
the **URL** (`ca_url_key` -- `AWS_SERVER_CA_CERT_PEM_URL`, `AZ_SERVER_CA_CERT_PEM_URL`) and the root
is fetched from it, once per run: a copy taken at create is the one thing that goes stale without
anyone touching it, since both providers rotate on their own clock. A PEM handed in directly still
wins over the download, and a URL blanked on purpose is answered with the refusal rather than the
built-in one behind the reader's back.

Either way libpq wants a path, so the certificate is written into a temporary directory for exactly
as long as the connection needs it -- the admin connections and the loader's alike, so a domain's
model, data and change sets go over the same TLS its system was created with. That path never
reaches a recorded URI: it belongs to one machine and one run.
