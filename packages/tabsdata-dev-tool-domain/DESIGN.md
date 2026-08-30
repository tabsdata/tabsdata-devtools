<!--
Copyright 2026 Tabsdata Inc.
-->

# domain

`tdd domain`: domains inside systems -- schemas, generated data, change sets -- provisioned from
manifests so a test suite gets the same data on every backend.

## Shape

- Toolset `systems`; depends on `deps-systems`, `common-core`, `common-systems`. Entry point
  calls `common.systems.main.run("domain")`.
- `bin-reqs`: `docker`, `op`. State: `<tdd_dir>/data/domain`.

## How it works

- Verbs: `create/destroy/status/models/create-model/create-data/modify-data`,
  `list/info/manifest/upgrade`; `--manifest` drives batches (this is how `xp` provisions).
- A domain's system descriptor must be readable (`_TDD_CRYPTO_KEY`); names are
  `<user>_<build>` unless given.
- Verbs whose backend/model declares another toolset (salesforce's data plane) are re-dispatched
  unchanged to `domain-sf` through `tdd-exe`; the caller never sees the hop.
