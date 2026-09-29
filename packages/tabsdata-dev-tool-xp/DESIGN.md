<!--
Copyright 2026 Tabsdata Inc.
-->

# xp

`tdd xp`: tabsdata-xp's `tdx-xp` ported -- run the example suites end to end against a tdkserver:
a suite is an ordered list of stages -- provision domains, create collections, register
functions, fire triggers, watch, change the data live -- that `run-suite` runs in order;
`one-shot` creates the instance, runs it and tears down, `bench` times the phases, `--dry-run`
prints the `tdd tdk`/`tdd domain` lines.

## Shape

- Toolset `xp`, its own; depends on `deps-xp` (pydantic, pyyaml, parquet-tools), `common-core`.
  Modules: `state`, `reporter`, `models`, `suites`, `pointers`, `shell`, `conn`, `lanes`,
  `domains`, `project`, `live`, `work`, `execute`, `cycle`. xp reaches `domain` and tdk through
  `tdd` and imports neither, so it shares no resolution with them: `parquet-tools`, for the
  suites' check scripts (which run on xp's python), caps pandas below 3, and that stays in this
  toolset instead of deciding every database driver's in `systems`, where xp lived before.
- The tabsdata-xp `suites/` and `connections/` trees are **carried by** the package and are the
  default. They live at `<repo>/xp-tool/` (excluded from ruff), where they are read and edited,
  and a wheel build copies them in beside the module (`force-include`); an editable install
  copies nothing -- a link has no build step to hook -- so there `builtin_root()` finds them at
  the repo root instead, probing for `suites/` to tell the layouts apart. Same arrangement as
  the smoke scripts and the shell package's assets.
- tabsdata-xp's `connectors` dir is split here into `container-connectors` (docker/local
  systems) and `cloud-connectors` (lanes needing a cloud store or warehouse: az, bigquery,
  databricks, gcs, s3, snowflake). clickhouse and starrocks are container-connectors although
  they stage through s3/az/gcs: the aks/eks/gke smoke runs take `cloud-connectors`, and those
  two are not to run there. `--suite <type>/<name>|<type>` selects under them or under `--suites-dir DIR`; `export-suites --dir DIR` copies them out.
- No `bin-reqs`: xp reaches tdk and tdkserver only through `tdd tdk`/`tdd tdkserver`,
  and those launchers declare the binaries themselves -- the requirement belongs to the
  command that runs the program. Pointers under `<tdd_dir>/data/xp`; a scratch dir per run
  under `/tmp/tdd-xp/`.
- Verbs: `list-suites`/`list-systems`/`export-suites`; `create-instance`; `run-suite` (the
  stages in order); the phase verbs `create-domains`, `create-project`, `run-project`,
  `monitor-project`, `live-domains`, each over every stage of its kind, and the matching
  `destroy-domains`/`destroy-project`/`destroy-instance`; `enable-function`/`disable-function`;
  `list-instances` and `list-projects` over the pointer store; `one-shot` and `bench` over the
  whole cycle. The phase verbs stay so a failed run can be finished or taken apart by hand;
  `run-suite` is safe to run again -- a domain or collection that exists is left alone, a
  function is registered with `--update`.

## How it works

- Talks to the server only through `tdd tdk` (`proc.tool_argv` -> `tdd-exe`), so xp needs neither
  tdk on its PATH nor tabsdata in its own toolset -- it needs a venv with tabsdata installed,
  the one the launcher picks and names (the last activated, managed by `tdd venv` or not). It
  provisions through `tdd domain create --manifest` (a domain-manifest stage) or the `tdd
  domain` calls a domains stage lists, and tears down with one `tdd domain destroy --manifest
  --format json`, parsing the batch events.
- `--profile NAME` is tdk's `--profile`: which connection the calls use, so two shells on one
  account each keep their own login. Absent, no option is passed and tdk uses its default
  connection. tdk attaches `--profile` to every command, not to the root group -- `tdk --profile
  P login` is refused, `tdk login --profile P` works -- so `shell.tdk_argv`, which builds every
  tdk argv, appends it last, past the verb; no call can miss it or misplace it; the verbs that reach tdk (`create-`/`destroy-`/`run-`/`monitor-project`,
  `run-suite`, `enable-`/`disable-function`, `one-shot`, `bench`) take it and hand it to their fan-out children. The domain verbs never
  reach tdk and do not take it.
- **A domain-manifest stage is the batch**: `{"domain-manifest": {"emit_ops": FILE?, "domains":
  [{"name", "system", "model"?, "data"?, "emit"?}]}}` -- an object, not a list, for the setting
  beside its entries. xp writes the entries as a manifest (`domains-<n>.yaml`: `name`, `sys`,
  `name-in-system`, `model`, `size`, `emit-ops`) and runs ONE `tdd domain create --manifest`, the
  toolkit's batch: every domain in parallel, heaviest backend first, chaining create ->
  create-model -> create-data, one step per domain. `data` is a size label (xs=1, s=10, m=100,
  l=1000, xl=10000 times ~100 rows). With `emit_ops`, each seeded domain whose `emit` is not
  false (default true) appends its seed's operations to a file of its own under the work dir --
  two processes appending to one file with no lock can interleave, and on Windows an append is
  not atomic at all -- and once the batch is done xp appends those files to `emit_ops` in the
  order listed, so the trail does not depend on which domain finished first. A failed batch
  appends nothing. The built-in suites use it; the manifest's key is `emit-ops` because every
  manifest key mirrors a flag, the suite's `emit_ops` because every suite key is `_`.
- **A domains stage is `tdd domain` calls**, spelled as a live entry spells one --
  `{"name", "command", "options"}`, run as `tdd domain <command> --domain <instance>_<name>
  <options...>`: a domain's `create` (`--sys SYSTEM`), then what fills it (`create-model --model
  M`, `create-data --size N [--emit-ops FILE]`, any data verb). Each domain's calls run in the
  order written, the domains side by side (bounded by `$TDD_PARALLELISM`), one step per call; the
  first failure stops the rest at their next call. xp adds `--name-in-system` to a create itself
  (`xp_<user>_<ts>_<tag>_<domain>`, unique per run and stable within one), so a suite may not;
  a domain's first call is its create, and a domain is created once. A domain whose create finds
  it already in the store is left alone, its other calls with it. It says what a manifest
  cannot -- any option, any data verb after the seed -- at the cost of the batch: each call is a
  child of its own, not heaviest first. Teardown, for both kinds, is one `destroy --manifest`
  over every created domain.
- **The project phase is fanned out except where order is meaning**: project -> groups ->
  collections in parallel -> functions **serial**, because registration order is what the
  dependency graph is built from -> triggers fired in batches gated by `detached` -> the
  transaction monitor. A monitor that exits non-zero is started again every 5s: it only reads,
  and on a cluster the usual cause is the port-forward dropping for seconds, which used to fail
  every lane watching at that moment while their transactions ran on. The run fails once the
  monitor has kept failing for 120s; a watch that lasted 30s reached the server and restarts
  that clock. tdk's own monitor rides out a short outage too (tabsdata-os `live_monitor`); this
  covers the tdk versions that do not.
- `--secret-env` names the variable holding the domain crypto key (default `_TDD_CRYPTO_KEY`)
  and maps it into that name for the `tdd domain` children. In a connection template
  `$secret:D<n>__KEY` resolves from the backing domain's descriptor (the environment as a
  fallback) into an inline `secret:VALUE`, and the document is piped to `tdk collection create
  --conn-file -` -- a credential is never written to disk. `${D<n>__KEY}`, in a template or in a
  function's source, interpolates plain, for a value that is a name rather than a secret (the D0
  domain's in-system name, say).

## Suite stages

A suite is an ordered **list of stages**, each an object holding one of `domain-manifest`,
`domains`, `collections`, `functions`, `triggers`, `monitor` (`true`), `live`, `sentinel` or
`execute`, plus `_`-prefixed annotations (`_comment`, `_copyright`; an object holding only those is a
comment). Kinds repeat, in any order the dependencies allow:

```
[
  {"domain-manifest": {"domains": [...]}},
  {"live": [{"name": "churn", "blocking": false, ...}]},
  {"collections": [...]},
  {"functions": [{"collection": "c", "functionpath": "...", "enabled": false}]},
  {"triggers": [...]},
  {"monitor": true},
  {"live": [{"name": "settle", "wait": ["churn"]}]},
  {"sentinel": [{"collection": "c", "table": "xp_sentinel_changes",
                 "wait_for_key": "done", "time_out": "10m"}]}
]
```

- **`run-suite` runs them in order**, one-shot through it: a domain-manifest stage is one batch,
  a domains stage runs its calls, the
  project is created before the first
  stage that talks to it, collections in parallel, functions serial, triggers in their gated
  batches, a monitor stage watches until the transactions finish. A live stage's background
  entries keep running through the stages after it -- the point of ordering: data changing
  while a collection is created or a stream publisher takes its initial snapshot -- and a later
  live stage may wait for them; the suite's end waits for whatever still runs, and a stage that
  fails stops them.
- **Checked when the suite is read**, besides each kind's own checks: exactly one kind per
  stage, and nothing named from a *later* stage -- a collection's domains, a function's
  collection, a live entry's domain. A name defined nowhere is left to the stage that uses it.
  Stage numbers in messages count every entry of the list, comments included: the number a
  reader counts to in the file.
- **The older single object is refused**, naming the list it ran as
  (`[{"domains"}, {"collections"}, {"functions"}, {"triggers"}, {"monitor": true}]`). It is
  still *recognised* -- by `list-suites`, which marks it, and by a suite dir -- so an old file is a
  loud error rather than a lane silently missing. The built-in suites were converted to exactly
  the stages they ran (empty kinds dropped); `examples/gen_examples.py` writes its 49 in the
  list form. Rejected: keeping both forms -- two ways to write a suite, and the old one cannot
  express order.
- **The phase verbs take every stage of their kind** (`create-domains` all domains stages,
  `live-domains` all live stages as one script); `bench` runs the phases in lockstep across its
  lanes and ignores the order. A suite dir under `run-suite` or one-shot is one lane per
  definition, each running its own stages -- lanes no longer move in lockstep.
- **A sentinel stage is a latch**: each entry holds until `wait_for_key` is in some version of
  `table` in `collection`, and fails the run once `time_out` has passed. The key is one
  `tdd domain sentinel-data --key` wrote at the source, which the functions carry through to a
  table of the project; the stage reads its `sentinel_key` column. Every committed version is
  read (`tdk table versions --max-result 0`, then `tdk table data --version V --sql ...` for the
  key), each once -- a stream publisher writes each flush as a version of its own, holding only
  that flush's rows, so the latest alone would miss a key flushed earlier. It polls every 5s;
  the entries run in turn, but a key that arrived while an earlier one was awaited is found on
  the first look. It is how a stage waits for data to have *arrived* rather than for a guessed
  pause. **The column is read as the table spells it**: DB2 upper-cases unquoted names, so its
  stream carries `SENTINEL_KEY`, and tdk's SQL (Polars) matches a column's case -- so the name
  comes from `tdk table schema` of the first readable version, matched case-insensitively, and
  is quoted in the query. Found on a real run, where every read of a DB2 table failed with
  "unable to find column" and the stage timed out saying "0 version(s) read": a version that
  cannot be read is retried, and the time-out now counts those and gives the last error. A
  table with no such column at all fails at once. It runs under `run-suite` (so one-shot); no phase verb takes it and `bench` ignores it.
- **Durations** -- a sentinel's `time_out`, a live `sleep` -- are `"<VALUE><UNIT>"` with unit `s`,
  `m` or `h` (`"90s"`, `"2m"`, `"1.5h"`), and nothing else: a bare number is refused when the
  suite is read, since nothing in it says what it counts. `sleep` was `sleep_secs`, a number of
  seconds; the one suite using it was converted.
- **A run has a working dir**, `<scratch>/work`, made on first use and kept with the scratch dir.
  A suite names it `${XP_WORK_DIR}` -- in a domain call's options (a domains stage's or a live
  entry's) and an execute entry's params -- and the run's project `${XP_PROJECT}`; they are
  replaced when the value is used (the dir is a run's; a suite is read before any run), and any
  other `${XP_*}` is refused when the suite is read. `--emit-ops ${XP_WORK_DIR}/ops.jsonl` on
  every data call, the seed's create-data included, is one trail of every operation a run
  applied, for a script to check against what came out the other end.
- **An execute stage runs check scripts**: `{"execute": [{"name", "py_script", "params": [...],
  "requirements": [{"name", "version"?}], "continue_on_fail": false}]}`. `py_script` is a `.py`
  in the suite dir (by convention `scripts/`), checked for when the suite is read, and run from
  the suite dir by `tdd _xp-execute` (its own bare toolset, built by tdd-install) with `params` as
  its argv; exit 0 passes. The one thing that venv gives a script is the `tdd` module -- `from
  tdd import tdd`, every tool one call away (`tdd("tdk", ...)`, `tdd("pqt", ...)`) -- so xp's own
  pins are not the scripts' (they were, run on xp's python). An entry with `requirements` (a
  version is an exact pin) runs in a one-off venv instead: `tdd _venv create --type uv` as
  `tdd-xp-execute-<run>-<entry>`, filled with `uv pip install`, deleted after the step whether
  the script passed or not; the prefix finds what a killed run left (`tdd venv list`). The
  script gets `XP_WORK_DIR`, `XP_PROJECT`, `XP_INSTANCE`, `XP_SUITE_DIR` and `tdd-exe` on its
  PATH. Its output is in run.log, its last lines the step's error. A failure stops the run;
  `continue_on_fail` lets the stages after it run and fails the run at the end -- a check that
  fails is never a green run. Rejected: a script that passes by printing, or a result file -- an
  exit code is what every tool already speaks. `container-connectors/scripts/verify_cdc_ops.py`
  is the first: the CDC stream's output against the trail, the snapshot as the state the
  operations before it leave, and the changes after it one by one in the same source
  transactions (cascades replayed before the snapshot; transactions paired by content, so one lost or extra is reported alone; what the database logs besides the trail -- the rows a cascade takes, an update that changed nothing -- is the suite's to say, `--cascades`/`--noops logged|unlogged`, with no default: a check that accepts either lets a stream drop what it should carry). Column names are compared without case -- db2 reports them upper-cased, the trail has the model's -- and a source transaction orders by what it is: a postgres xid, a mysql GTID's sequence, db2's 32 hex digits as a string. Every change is checked by its whole row images -- the before-image all columns of the row as the trail left it, an update's row all columns after it -- since a table without a key is known to a stream by nothing less; an update that sets a key column moves the row to its new key. `--start initial-load|head|tail` says what precedes the changes: a snapshot, the seed replayed from the log's head (checked as a snapshot is), or nothing. The CDC suites all run over `employeescdc`, a model made for them: a primary key every update changes, a composite one, a table with only a unique index and one with no key at all -- the employees model has only single keys no change touches.
- **`"enabled": false`** on a function registers it with `tdk fn register --disabled`: a stream
  publisher does not start until `enable-function --project P --collection C --function F`
  (tdk's `fn enable`); `disable-function` stops one. A group project is refused -- its lanes'
  functions are each their own.

## Live domains

A suite's `live` stages hold a script: the `tdd domain` data verbs (`create-model`, `create-data`,
`modify-data`, `sentinel-data`, `delete-data`, `delete-model` -- never `create`/`destroy`, the
domain's lifecycle is xp's) run against its domains while the project is up, so a stream
publisher or a re-triggered publisher sees its source change the way a real one does. Every
entry has a `name` (a letter, then letters, digits, `_`, `-`; unique across the whole script)
and is one of four kinds:

```
{"name", "domain": {"name", "command", "options": ["--sets", "5"]}, "blocking": true|false}
{"name", "sleep": "<VALUE><UNIT>"}
{"name", "wait": [NAMES]}
{"name", "repeat": N, "live": [...], "blocking": true|false}
```

A domain entry is one call, `tdd domain <command> --domain <instance>_<name> <options...>`, the
options the words as typed (`--domain`, `--format`, `--latch`, `--verbose` are xp's and refused)
-- the same object a domains stage lists, limited to the data verbs; nothing is filled in from
the domains stage, so a live create-model names its `--model`. A repeat entry runs its nested
`live` N times (default 1). **Blocking** is the default: the script runs the entry to the end
before going on. `"blocking": false` starts it on a thread
of its own and the script goes straight on, side by side, until a `wait` names it. **A script --
the whole one, or one pass of a repeat -- is complete when everything it started has finished**:
its end waits for what still runs, so nothing outlives the loop that started it, and
`live-domains` returns once the data has stopped changing.

- **A wait reaches back, not in**: it names domain or repeat entries *before* it in its own list
  or in an enclosing one. Those have been started, on this path, by the time the wait is reached.
  A name inside another entry's nested `live` may not have started yet, or may start again; the
  entry that contains the wait would be waiting for itself. Each pass of a repeat has its own
  scope, so a name means that pass's run. Rejected: waits reaching anywhere, which needs a rule
  for "which run of a block nested in a loop" and can deadlock.
- **Validated when the suite is read**: a missing or reused name, not exactly one kind, an unknown
  verb or domain, a reserved option, `repeat` without `live`, `blocking` on a sleep or wait, a
  wait out of reach or naming a sleep or wait -- `create-instance` refuses, not pass 7 of a loop
  20 minutes in. Unknown keys are refused too: a typo is not a silently ignored option.
- **Every call is one step**, labelled with the entries and passes it is under
  (`cycle 2/3 > churn 7/10 > change`). A background entry runs on a thread, not in a bounded pool:
  entries wait for one another, and a pool full of waiters would never run what they wait for.
  **The first failure anywhere stops the script**: every entry still running stops at its next
  step or pause (the `tdd domain` call in flight finishes -- a change set is not killed half way),
  nothing later starts, and that failure is the run's error.
- **`--dry-run` prints the calls in script order**, the pauses as `sleep N`, and where an entry
  goes to the background, ends or is waited for as `#` comments. A shell rendering with
  subshells was the first version and was dropped with nested waits: a subshell cannot `wait` on
  a pid its parent started.
- **Where it runs is the suite's stage order**: a `live` stage wherever the list puts it. `--no-live`
  skips every live stage. A monitor stage sees what has started when it begins: a stream that
  buffers its changes needs the live stage before it to end with a `sleep` long enough for the
  last flush -- or, better, a sentinel stage waiting for a key written after the last change.
  `live-domains --instance I` runs every live stage as one script, over a group's lanes too;
  `bench` does not run it -- its phases are timings, and a script's pauses would be what they
  measured.

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
written at the end and becomes the fields of the run's final `ok`/`error`. A monitor that finds
failed transactions saves each one's worker logs to `<scratch>/trx-logs/<trx>/<worker>.log`
before it fails, and names them in errors.log: a one-shot or smoke run destroys the instance
next, and the workers with it. It fetches per worker (`worker list --trx`, `worker logs
--worker`) because `trx logs` prompts for a pick when several ran. Every run gets one
scratch directory under `/tmp/tdd-xp/`, announced at startup and **never deleted** -- the
manifests it authored, the logs, the report, and one subdir per lane.

`list-systems --suite S` is the pre-flight: every system the suite's domains name, with its type
from `tdd system list`, `ok` or `MISSING`. One missing system fails it, so a run does not spend
minutes on an instance whose lanes cannot provision.
