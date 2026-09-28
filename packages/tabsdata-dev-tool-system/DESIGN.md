<!--
Copyright 2026 Tabsdata Inc.
-->

# system

`tdd system`: external systems for testing -- databases in docker, object stores, warehouses,
kafka, credential-only services -- created, inspected and destroyed from one place, with their
connection details kept as encrypted descriptors.

## Shape

- Toolset `systems` (Python 3.12: several drivers ship no wheels for the newest CPython);
  depends on `deps-systems`, `common-core`, `common-systems`. Entry point calls
  `common.systems.main.run("system")`.
- `bin-reqs`: `docker`, `op`. State: `<tdd_dir>/data/system`.

## How it works

- Verbs: `create/destroy/status/purge/restart/fetch-bin/connect`, `types/1p-template/list/info/
  manifest/upgrade`. Talking to 1Password is not a system verb: `secrets` and `crypto-key` moved
  to `tdd _1p fetch`, which `tdd env set --crypto/--secrets` applies, and `1p-set` to `tdd _1p
  set` (2026-09-28) -- none touches a store or a backend, and each put an `op` call in the
  `systems` env. What stays is what needs a backend: `1p-template` and `info --format 1p`, which
  write a system's item.
  `clean-docker [--yes|-y]` stops and deletes every `tdd_*` container -- the prefix all
  docker-backed systems use -- descriptor or not; it lists them and asks first unless `--yes`.
- **The five postgres types are one shape** (`systems/postgres/backend.py`, which
  `ManagedPostgres` extends): `postgres` and `postgrescdc` are containers, `awspostgres`,
  `gcppostgres` and `azpostgres` managed instances, and every one of them records the same
  block -- `INTERNAL_HOST`/`EXTERNAL_HOST`, `PORT`, `DATABASE`, `USER`, `PASSWORD`, `VERSION`
  (probed at create) and a `SQLALCHEMY_URI`/`URI` pair per plane -- plus only its own group
  (`DOCKER_CONTAINER_NAME`/`_ID`, or `AWS_*` / `GCP_*` / `AZ_*`, and the TLS pair on the
  managed three). Which plane a reader wants is the reader's property, not the instance's, so
  neither is unqualified; a container has one address and records it under both names.
  Everything tdd does itself -- probe, status, DDL, loading a model -- goes over the external
  plane, since that is where tdd is. A domain carries the block with its own database and owner
  in it. All five hold models and data; the managed three borrow the plain system's DDL
  (`ddl_from_slug`) and get the root certificate written to a temporary file for the length of
  a load (`data_plane_uri`, a context manager for exactly that reason).
- **1Password is a shape, not an integration** (`common.systems.onepassword`). `tdd _1p fetch
  --secrets 1p:VAULT` reads a vault into `<ITEM_TITLE>__<FIELD_ID>` variables, which are the
  `$<PREFIX>__<KEY>` a type's env-sourced options read; `--format 1p` writes that mapping the
  other way. `1p-template --type T` produces the item for a type before any system exists, and
  `info --sys S --format 1p` the same item carrying what the system actually has. `1p-template`
  speaks the item and nothing else, so it takes no `--format` at all. The title *is* the prefix (`--prefix` overrides it), a
  field id is its meta key lower-cased, a secret option is `CONCEALED`, and a
  host/port/user/password type is 1Password's `DATABASE` item rather than an `API_CREDENTIAL`
  -- no type has that shape today (the postgres family names two hosts, and `external_host` is
  not 1Password's `hostname`), so every item is a credential; the branch stays for a type that
  does. A backend's `onepassword_skip` keeps an option out of the item (`gcppostgres` and
  `azpostgres` carry their server CA as the certificate, never the local path to a copy;
  `awspostgres` carries neither, since RDS's is a download); a computed default is written in
  rather than left as `?`, which would be read back as the literal string.
- `tdd _1p set --vault 1p:V --entry PATH|-` files such an item, closing the loop: `1p-template`
  writes it, `_1p set` puts it in the vault, `_1p fetch --secrets` reads it back as the variables
  `create` needs. How it files (delete, then create; the item on stdin) is in the `_1p` design doc.
- Every descriptor read or write needs `_TDD_CRYPTO_KEY`; `create --force` replaces a descriptor
  an older key left unreadable.
- **A verb exists when some type exposes it**, gated on a capability: `purge` on
  `supports_purge`, `restart` and `connect` on `is_container`. `fetch-bin` is ungated on purpose,
  so `--type ALL` is the handy way to pull every image at once and a type with none is warned and
  skipped rather than failing the run. A verb aimed at a system that does not have it is rejected
  naming what that system does support.
- Batch verbs run children through `tdd-exe` in parallel (`TDD_PARALLELISM`), heaviest first,
  and re-emit their events. The selector is `--type` for `create` (one system per type, named
  after it) and `--sys` for everything else, each a name, a comma list or `ALL`; `--sys-prefix P`
  prepends `P_`, `--manifest FILE` replays a YAML manifest (`--sync` reconciles the store to it),
  `--fail-fast` stops at the first failure and `--report FILE` writes a JSON run record. Before
  any child starts, the parent parses each child's argv with the parser that child builds (per
  type, bound to its descriptor): an option no target takes is one error, not a failure per
  child after the batch has begun. A target the store lacks, a verb its type lacks, or a type in
  another toolset is left to its child, as before. Parallel
  creates cannot compete for ports: every type owns a fixed slot, and `--ports` pins them.
- The long verbs (`create`, `destroy`, `purge`) take `--latch FILE` so a background run is
  waitable, and their chatty detail goes to `/tmp/tdd-system-<verb>-...` while the console keeps
  to brief progress.
- All logic is in `common-systems`; this package exists so the tool has a name, a toolset and a
  requirements file.
