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
- `bin-reqs`: `docker`; `op` optional, checked where 1Password is read -- Windows has none. State: `<tdd_dir>/data/domain`, one encrypted descriptor per
  domain, addressed by name.

## How it works

- Verbs: `create/destroy/status/models/create-model/create-data/modify-data/sentinel-data/
  delete-data/delete-model/capture-table/release-table`, plus
  `types/list/info/manifest/upgrade` and the shared `config`. A domain's name is `<user>_<build>`
  unless given, and its system's descriptor must be readable first (`_TDD_CRYPTO_KEY`, which
  every store-reading verb requires before it runs).
- **A verb exists when some backend exposes it.** The catalog gates each one on a capability
  (`supports_models`, `supports_data`, `supports_changes`, `supports_table_capture`), and a
  verb aimed at a system that does not have it is rejected naming what that system does
  support -- rather than the verb simply not existing, which would read as a typo.
- **A test's own CDC source table goes through the backend.** `capture-table --table T
  [--ddl SQL]` creates `T` in the domain's schema when given its DDL, registers it for change
  capture by the same sequence `create-model` runs for the model's tables, and reports the CD
  table in its ok event; `release-table --table T [--drop]` undoes it, best-effort, so a test's
  teardown never fails on a half-made registration. Only `db2cdc` captures this way today.
- **Batches are the normal case.** `--domain NAME|d1,d2|ALL` on any verb, `--sys` on `create`
  (one domain per system, named after it), `--manifest FILE` on `create` to replay a YAML
  manifest (`--sync` reconciles the store to it) and on `destroy/status`. Targets run in parallel
  in their own `tdd-exe` children, heaviest first, bounded by `$TDD_PARALLELISM`, and their
  events are re-emitted by the parent; `--fail-fast` stops at the first failure and
  `--report FILE` writes a JSON run record. This is how `xp` provisions. A domain entry's
  `emit-ops: FILE` goes to its create-data step (`--emit-ops FILE`), not to create: the seed's
  operations appended for a caller to check.
- **The model and its data come off as they went on.** `delete-data` empties the model's
  entities and keeps them -- the domain is left as `create-model` leaves it, so `create-data`
  follows without `--force` -- and it is the schema dropped and installed again, not a `DELETE`
  per entity, because that reload is already right for every backend (staged files, topics, CDC
  registrations). `delete-model` drops the entities and forgets the model through the backend's
  `uninstall_schema`; the domain itself stays for `destroy`. Both refuse a domain with no model
  and neither minds one with no data, so a loop may delete on every pass.
- **`--entity` is ALL, one entity, or a comma list** -- ALL narrowed to those, each taking its
  per-set rows as ALL does -- so a run can change every table but one, and that table sees no
  change for as long as the runs leave it out (`cdc/<source>_quiet_table`). One entity keeps
  its meaning: `--sets` is its row count.
- **modify-data's targets are the seeded rows**, the ones `Entity.target` addresses, counted
  by what create-data loaded (`seeded` in the descriptor) rather than today's counts, which
  drift with every insert and delete. DELETEs walk in from the tail, each seed taking its own
  block (`seed x deletes-per-run`), so `--seed AUTO` passes delete a distinct row each time
  and stop -- plan and report none -- once the seeded rows are used up; UPDATEs walk from the
  head over the rows those deletes have not reached. The old walk offset the seed against the
  current count, and a Mix pass (one row and one seed more) deleted the same row forever. The
  walk assumes the domain's earlier passes were consecutive seeds of the same shape, which is
  what AUTO produces; a descriptor from before `seeded` bounds by its current counts.
- **modify-data's transactions are serial, interleaved, nested or a mix** (`--trx-mode`,
  default `serial`), on the SQL engines (`supports_trx_modes`: the container databases and the
  managed postgres three; a file or kafka domain, a warehouse or an OLAP store refuses anything
  else). `--trx-concurrency N` (default 4) is how many are open at once. `interleaved` keeps
  up to N open on connections of their own and runs one statement from each in turn; a
  transaction commits right after its last statement and the next pending one begins in its
  place, so commits land between the others' statements and come in start order. `nested`
  begins each transaction after one statement of the one before it, down to the innermost
  (N deep), which finishes and commits first; then each enclosing one finishes and commits --
  commits in reverse start order, every life inside the one begun earlier, the shape a
  change-data-capture consumer that delivers by commit must reorder. `mix` takes the
  transactions in groups of N, each group the next of serial, interleaved, nested, round and
  round -- as `--ops Mix` cycles the verbs over the sets -- so one run leaves every shape
  behind (the detail log names each group). One thread drives the schedule (`trx.schedule`, a pure function of the
  plan, so a dry run says exactly what a real one would do; `sql_runner.run_sql_schedule`
  executes it, every step in the detail log). Rejected: threads -- a real race is not
  repeatable, and repeatability is what the seeds buy. The one thing one thread cannot do is
  wait for itself: a statement blocked by a row another of the run's open transactions holds
  would wait for a commit that cannot come, so a plan that writes one row from two transactions
  is refused up front (`trx.contention`, which only the update walk wrapping past a table's
  live rows produces), and every concurrent connection gets the dialect's lock-wait timeout
  (`concurrent_session_setup`, `LOCK_WAIT_SECONDS`) so anything else -- a parent deleted while
  a child inserted under it is open, a table scanned for a key it has no index on, another
  session -- ends as an error naming the statement rather than a hang. MySQL's concurrent
  connections also run READ COMMITTED: under REPEATABLE READ a write that scans a keyless
  table (employeescdc's `readings`) locks every row it reads. Even under READ COMMITTED a
  DELETE on such a table still locks each row it scans, on MySQL and on Db2 (`scan_locks`),
  so it waits on any row another open transaction wrote there: before such a schedule runs,
  the backend reflects which written tables have neither a key nor a unique index (Db2 in the
  domain's `currentSchema`) and replays the schedule (`trx.scan_waits`), refusing the first
  DELETE that would wait, by table and transactions. A nest never meets one -- its
  transactions all begin on another table -- an interleaved run does in its first round; an
  UPDATE passes such rows by (it reads their last committed version), so only DELETE counts.
  The CDC suites change that table in a serial pass of its own beside an interleaved or mix
  churn there. Oracle has no DML lock-wait
  timeout, so there only the refusal stands between a contended plan and a wait. Serial is
  untouched by any of this.
- **The data verbs report the same shape**: `trx_mode`, `transactions`, `trx_concurrency` and
  `entities` -- `{name: {insert, update, delete, rows}}`, `rows` the entity's count once the
  run is applied (absent under `--dry-run`); the view prints one aligned line per entity.
  create-data is always one serial transaction and says so, so a reader of either report reads
  one field. The trail (below) carries `trx_mode` and goes out in commit order.
- **`--dry-run` plans; `--emit-ops FILE` keeps the trail.** `create-data`, `modify-data` and
  `sentinel-data` take both. `--dry-run` works out the operations and applies none: neither
  the system nor the descriptor is touched, so `--seed AUTO` does not advance and
  `create-data` needs no `--force`; on its own it writes no file. `--emit-ops FILE` APPENDS the
  operations as CDC-style JSON lines -- `run` (an id per run: two runs of a verb can share
  a second, and so a `ts`), `ts`, `domain`, `verb`, `seed` and `trx_mode`
  (modify-data), `dry_run`, `txn` (numbered from 0 within the run), `commit` (modify-data: the
  transaction's rank in the run's commit order, which is the order the lines are written in,
  so under `nested` `txn` counts down), `op`, `entity`, then `row` for an insert,
  `key` + `set` for an update, `key` for a delete -- after a real run has applied them, or as
  planned under `--dry-run`. Appending is what lets one file be the trail of a whole live
  script, or of a batch: each run's lines go out in one `O_APPEND` write, so runs sharing the
  file do not interleave. A failed run writes nothing. Salesforce refuses both, its records
  existing only inside the load.
- **Every model carries an empty `xp_sentinel`** (`sentinel_key` VARCHAR(255), the primary
  key where the backend has one; `sentinel_ts` TIMESTAMP), in its `entities.json` and in every
  DDL of it. Only `sentinel-data --key KEY` writes it: one row, the key at the current UTC
  second, through `apply_changes`, so a test can mark a point in its run and wait for that key
  downstream. It needs the model, not data; no generator builds it and no `Entity` declares it,
  so create-data leaves it empty (its count carried, unless a reload dropped it) and modify-data
  never picks it. A repeated key is refused on SQL, appended on the file and kafka backends.
  Gated like modify-data; salesforce's model has none, its objects living in the org.
- **The long verbs are waitable.** `create`, `destroy`, `create-model`, `create-data`,
  `modify-data`, `sentinel-data`, `delete-data` and `delete-model` take `--latch FILE`, and their chatty detail goes to `<temp>/tdd-domain-<verb>-...`
  while the console keeps to brief progress.
- **Toolset hops are invisible.** A backend declares the toolset its data plane needs
  (`dom_toolset`) and a model may override it (`models/<model>/model.json`); when that is not the
  toolset this tool runs in, the invocation is re-dispatched unchanged to the sibling registered
  for it (`domain-sf` for salesforce) through `tdd-exe`, carrying `--format` so the child speaks
  for the run. Without `TDD_DIR` there is nothing to dispatch through, and that is the error.
- Implementations resolve per system: `systems/<slug>/<verb>.py` when a backend overrides one,
  else the shared `_common/commands`, and `-h` prints the named target's own (`--sys` on
  create, `--domain` otherwise) -- the first type's when the store lacks it, cannot read it
  without the key, or the selector is a batch, since help asks for neither. redpanda's own add options: `create-model
  --up-to-partitions N`, `create-data`/`modify-data --entity A,B` and `--schema-changes`;
  postgresnative's `create --pgvector on|off` (default off) creates the pgvector extension in
  the domain's database and records `PGVECTOR`, a manifest entry's `pgvector: on` replaying it
  (common-systems' DESIGN.md).
