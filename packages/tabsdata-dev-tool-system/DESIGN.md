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

- Verbs: `create/destroy/status/purge/restart/fetch-bin/connect`, `types/list/info/manifest/
  upgrade`, `secrets` and `crypto-key` (`--as json|export|unset`, which `tdd env set` evals).
- Every descriptor read or write needs `_TDD_CRYPTO_KEY`; `create --force` replaces a descriptor
  an older key left unreadable.
- Batch verbs run children through `tdd-exe` in parallel (`TDD_PARALLELISM`), heaviest first,
  and re-emit their events.
- All logic is in `common-systems`; this package exists so the tool has a name, a toolset and a
  requirements file.
