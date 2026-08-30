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
  csv/ddl carry no header).
- Ranges on pydantic, pyyaml, cryptography; joins only the toolsets whose tools depend on it.

## How it works

- Descriptors under `<tdd_dir>/data/system` and `data/domain` are encrypted with
  `_TDD_CRYPTO_KEY` (`tdd env set --crypto`; 1Password field `TD_BACKENDS_CRYPTO_KEY`).
  A shell still exporting the old name is told what to run.
- A backend names the toolset each plane needs (`sys_toolset`/`dom_toolset`); when a domain verb
  belongs to another toolset, `domain` re-dispatches through `tdd-exe` to `domain-sf`.
- A system's own config comes from `<SYSTEM>__<KEY>` variables (`S3__BUCKET`,
  `DRUID__ROUTER_PORT`); `secrets` loads them from 1Password.
- Output follows the guidelines through the `console` adapter; chatty verbs log to
  `/tmp/tdd-<tool>-<verb>-<name>-<stamp>.log`, which is also the failure log.
- Domain names are `<user>_<build>` from `TD_BUILD_USER`/`TD_BUILD_NUMBER` (else login/0).
