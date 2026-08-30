<!--
Copyright 2026 Tabsdata Inc.
-->

# xp

`tdd xp`: tabsdata-xp's `tdx-xp` ported -- run the example suites end to end against a tdkserver:
provision domains, create the project, register functions and triggers, run, check, tear down;
`one-shot` does the cycle, `bench` times it, `--dry-run` prints the `tdd tdk`/`tdd domain` lines.

## Shape

- Toolset `systems`; depends on `deps-systems` (pydantic, pyyaml), `common-core`. Modules:
  `state`, `reporter`, `models`, `suites`, `pointers`, `shell`, `conn`, `lanes`, `domains`,
  `project`, `cycle`.
- The tabsdata-xp `suites/` and `connections/` trees ship inside the package (`xp/`, excluded
  from ruff) and are the default; tabsdata-xp's `connectors` dir is split here into
  `container-connectors` (docker/local systems) and `cloud-connectors` (lanes needing a cloud
  store or warehouse: az, bigquery, clickhouse, databricks, gcs, s3, snowflake, starrocks); `--suite <type>/<name>|<type>` selects under them or under
  `--suites-dir DIR`; `export-suites --dir DIR` copies them out.
- `bin-reqs`: `tdk`, `tdkserver`. Pointers under `<tdd_dir>/data/xp`; a scratch dir per run
  under `/tmp/tdd-xp/`.

## How it works

- Talks to the server only through `tdd tdk` (`proc.tool_argv`), so `TDD_VENV` must name a venv
  with tabsdata installed; provisions through `tdd domain create|destroy --manifest --format
  json`, parsing the batch events.
- `--secret-env` names the variable holding the domain crypto key (default `_TDD_CRYPTO_KEY`)
  and maps it into that name for the `tdd domain` children.
- A suite *dir* fans out one lane per file: child `xp` processes run in parallel
  (`TDD_PARALLELISM`), their events re-emitted tagged `xp: step|note|summary`. Children nest
  their scratch under the parent's through `_TDD_XP_SCRATCH`, honoured only with the parent's
  pid in `_TDD_XP_PARENT`; a stale export is reported and ignored.
- Connection templates resolve `$secret:KEY` from the domain descriptor, then the environment.
- `list-systems --suite S` is the pre-flight: every system the suite's domains name, with its
  type from `tdd system list`, `ok` or `MISSING`; one missing system fails it, so a run does not
  spend minutes on an instance whose lanes cannot provision.
