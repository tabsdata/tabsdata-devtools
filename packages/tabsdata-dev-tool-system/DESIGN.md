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
  manifest/upgrade`, `secrets` and `crypto-key` (`--format export`, which `tdd env set` evals).
  `clean-docker [--yes|-y]` stops and deletes every `tdx2*` container -- the prefix all
  docker-backed systems use -- descriptor or not; it lists them and asks first unless `--yes`.
- **1Password is a shape, not an integration** (`common.systems.onepassword`). `secrets --set
  1p:VAULT` reads a vault into `<ITEM_TITLE>__<FIELD_ID>` variables, which are the
  `$<PREFIX>__<KEY>` a type's env-sourced options read; `--format 1p` writes that mapping the
  other way. `1p-template --type T` produces the item for a type before any system exists, and
  `info --sys S --format 1p` the same item carrying what the system actually has. `1p-template`
  and `1p-set` speak the item and nothing else, so neither takes a `--format` at all. The title *is* the prefix (`--prefix` overrides it), a
  field id is its meta key lower-cased, a secret option is `CONCEALED`, and a
  host/port/user/password type is 1Password's `DATABASE` item rather than an `API_CREDENTIAL`.
  A backend's `onepassword_skip` keeps an option out of the item (`gcppostgres` carries its server
  CA as the certificate, never the local path to a copy); a computed default is written in rather
  than left as `?`, which would be read back as the literal string.
- `1p-set --vault V --entry PATH|-` files such an item, closing the loop: `template` writes it,
  this puts it in the vault, `secrets` reads it back as the variables `create` needs. Always a
  delete then a create -- `op item create` files a *second* item under a title that already
  exists, and a vault with two `S3` items reads back a coin toss; what it replaces stays in
  Recently Deleted for 30 days. The item is piped to `op` (`item create -`), so it reaches it
  through neither argv nor a file, and is refused before the delete if it is not an item. What is
  uploaded is `title`/`category`/`fields` and no field `reference`, so a whole `op item get
  --format=json` can be handed straight back -- the rest of it describes the item it was read
  from.
- Every descriptor read or write needs `_TDD_CRYPTO_KEY`; `create --force` replaces a descriptor
  an older key left unreadable.
- Batch verbs run children through `tdd-exe` in parallel (`TDD_PARALLELISM`), heaviest first,
  and re-emit their events.
- All logic is in `common-systems`; this package exists so the tool has a name, a toolset and a
  requirements file.
