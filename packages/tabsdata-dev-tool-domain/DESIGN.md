<!--
Copyright 2026 Tabsdata Inc.
-->

# domain

`tdd domain`: domains inside systems -- schemas, generated data, change sets -- provisioned from
manifests so a test suite gets the same data on every backend.

## Shape

- Toolset `systems`; depends on `deps-systems`, `common-core`, `common-systems`. Entry point
  calls `common.systems.main.run("domain")` and says nothing else: the family lives in
  `common-systems`, shared with `system` and `domain-sf`, and this package exists so the command
  has a name, a toolset and a `bin-reqs`.
- `bin-reqs`: `docker`, `op`. State: `<tdd_dir>/data/domain`, one encrypted descriptor per
  domain, addressed by name.

## How it works

- Verbs: `create/destroy/status/models/create-model/create-data/modify-data`, plus
  `types/list/info/manifest/upgrade` and the shared `config`. A domain's name is `<user>_<build>`
  unless given, and its system's descriptor must be readable first (`_TDD_CRYPTO_KEY`, which
  every store-reading verb requires before it runs).
- **A verb exists when some backend exposes it.** The catalog gates each one on a capability
  (`supports_models`, `supports_data`, `supports_changes`), and a verb aimed at a system that
  does not have it is rejected naming what that system does support -- rather than the verb
  simply not existing, which would read as a typo.
- **Batches are the normal case.** `--domain NAME|d1,d2|ALL` on any verb, `--sys` on `create`
  (one domain per system, named after it), `--manifest FILE` on `create` to replay a YAML
  manifest (`--sync` reconciles the store to it) and on `destroy/status`. Targets run in parallel
  in their own `tdd-exe` children, heaviest first, bounded by `$TDD_PARALLELISM`, and their
  events are re-emitted by the parent; `--fail-fast` stops at the first failure and
  `--report FILE` writes a JSON run record. This is how `xp` provisions.
- **The long verbs are waitable.** `create`, `destroy`, `create-model`, `create-data` and
  `modify-data` take `--latch FILE`, and their chatty detail goes to `/tmp/tdd-domain-<verb>-...`
  while the console keeps to brief progress.
- **Toolset hops are invisible.** A backend declares the toolset its data plane needs
  (`dom_toolset`) and a model may override it (`models/<model>/model.json`); when that is not the
  toolset this tool runs in, the invocation is re-dispatched unchanged to the sibling registered
  for it (`domain-sf` for salesforce) through `tdd-exe`, carrying `--format` so the child speaks
  for the run. Without `TDD_DIR` there is nothing to dispatch through, and that is the error.
- Implementations resolve per system: `systems/<slug>/<verb>.py` when a backend overrides one,
  else the shared `_common/commands`.
