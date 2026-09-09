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
- The tabsdata-xp `suites/` and `connections/` trees are **carried by** the package and are the
  default. They live at `<repo>/xp-tool/` (excluded from ruff), where they are read and edited,
  and a wheel build copies them in beside the module (`force-include`); an editable install
  copies nothing -- a link has no build step to hook -- so there `builtin_root()` finds them at
  the repo root instead, probing for `suites/` to tell the layouts apart. Same arrangement as
  the smoke scripts and the shell package's assets.
- tabsdata-xp's `connectors` dir is split here into `container-connectors` (docker/local
  systems) and `cloud-connectors` (lanes needing a cloud store or warehouse: az, bigquery,
  clickhouse, databricks, gcs, s3, snowflake, starrocks); `--suite <type>/<name>|<type>`
  selects under them or under `--suites-dir DIR`; `export-suites --dir DIR` copies them out.
- No `bin-reqs`: xp reaches tdk and tdkserver only through `tdd tdk`/`tdd tdkserver`,
  and those launchers declare the binaries themselves -- the requirement belongs to the
  command that runs the program. Pointers under `<tdd_dir>/data/xp`; a scratch dir per run
  under `/tmp/tdd-xp/`.
- Verbs, in the order a run uses them: `list-suites`/`list-systems`/`export-suites`;
  `create-instance`, `create-domains`, `create-project`, `run-project`, `monitor-project`, and
  the matching `destroy-domains`/`destroy-project`/`destroy-instance`; `list-instances` and
  `list-projects` over the pointer store; `one-shot` and `bench` over the whole cycle. Every
  phase is a verb of its own so a failed run can be resumed at the phase that failed rather than
  from the beginning.

## How it works

- Talks to the server only through `tdd tdk` (`proc.tool_argv` -> `tdd-exe`), so xp needs neither
  tdk on its PATH nor tabsdata in its own toolset -- it needs `_TDD_VENV` to name a venv with
  tabsdata installed, which the launcher checks. It provisions through `tdd domain
  create|destroy --manifest --format json`, parsing the batch events.
- **The domains phase is one call, not a loop**: xp writes a manifest into its scratch dir and
  hands it to `tdd domain create --manifest`, the toolkit's own batch entry point, which runs
  every entry in parallel, heaviest backend first, chaining create -> create-model ->
  create-data. Domains already in the store are left alone; teardown is `destroy --manifest`.
- **The project phase is fanned out except where order is meaning**: project -> groups ->
  collections in parallel -> functions **serial**, because registration order is what the
  dependency graph is built from -> triggers fired in batches gated by `detached` -> the
  transaction monitor.
- `--secret-env` names the variable holding the domain crypto key (default `_TDD_CRYPTO_KEY`)
  and maps it into that name for the `tdd domain` children. In a connection template
  `$secret:D<n>__KEY` resolves from the backing domain's descriptor (the environment as a
  fallback) into an inline `secret:VALUE`, and the document is piped to `tdk collection create
  --conn-file -` -- a credential is never written to disk. `${D<n>__KEY}`, in a template or in a
  function's source, interpolates plain, for a value that is a name rather than a secret (the D0
  domain's in-system name, say).

## Suites, lanes and pointers

A selector is `<type>/<name>` for one definition or `<type>` for a **directory**, which fans out
to one instance and project per definition file in it -- a "swim lane". A selector that resolves
to nothing names the suite it probably meant (`--suite s3` -> `cloud-connectors/s3`) rather than
only pointing at `list-suites`: the name alone is what a reader remembers, and it is exactly the
shape that stopped working when the connectors were split in two. Offered, never accepted -- a
bare name is unique today and need not stay so. Each lane is a normal
single-lane `xp` child run with `--format json`, so the parent aggregates their event streams
live under a running total (`TDD_PARALLELISM` bounds them). `--fail-fast` lets the first failure
kill the rest; without it every lane is attempted, and a multi-phase run records the lanes that
died against their phase, drops them from later phases and reports them once at the end. Children
nest their scratch under the parent's through `_TDD_XP_SCRATCH`, honoured only with the parent's
pid in `_TDD_XP_PARENT`, so a stale export is reported and ignored.

The pointer store is `<tdd_dir>/data/xp/`: `i-<I>` for an instance (a definition file is recorded
as its path and re-read live; a directory records one member pointer per lane plus a group
pointer), `p-<P>` for a project naming its instance or group -- so every later verb needs only
`--project`. `connections/` templates are found by walking up from the suite dir to the first
ancestor holding one, else the built-in ones.

## Progress, logs and the report

One **step** is one unit of a suite's work: a domain, the project, a collection group, a
collection, a function registration, a trigger, the monitor wait. A command declares how many it
is about to run and wraps each one, which times it and reports it *as it finishes* as an event
whose message is the progress line and whose fields carry the structured step -- which is exactly
what the lane dispatcher reads back. The detail (every command and its output) goes to
`<scratch>/run.log` and never to the console; failures alone also go to `<scratch>/errors.log`,
created on the first one, so its existence answers "did this run go wrong"; `report.json` is
written at the end and becomes the fields of the run's final `ok`/`error`. Every run gets one
scratch directory under `/tmp/tdd-xp/`, announced at startup and **never deleted** -- the
manifests it authored, the logs, the report, and one subdir per lane.

`list-systems --suite S` is the pre-flight: every system the suite's domains name, with its type
from `tdd system list`, `ok` or `MISSING`. One missing system fails it, so a run does not spend
minutes on an instance whose lanes cannot provision.
